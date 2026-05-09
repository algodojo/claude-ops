# AGENTS.md

Guidance for AI coding agents working on this repository. Security is the top priority; correctness and ergonomics come after. If a request conflicts with a rule here, stop and surface the conflict to the user before proceeding.

## What this project is

`claude-ops` provisions a remote Claude Code workstation on a VPS using Pulumi for infrastructure-as-code and Tailscale for the only network ingress. The user runs `pulumi up` and ends up with a hardened VM reachable only over their tailnet, with Claude Code installed and ready to use.

Design north star: **`pulumi up` on a clean machine should produce a VPS that has no public services other than what Tailscale itself requires for outbound bring-up.**

## Stack & provider specifics

Locked-in choices for this project. Don't reach for alternatives without explicit user agreement.

- **Pulumi language**: Python, managed end-to-end with [uv](https://docs.astral.sh/uv/). `uv` owns Python version selection (`infra/.python-version`), top-level deps (`infra/pyproject.toml`), and a hash-verified lockfile (`infra/uv.lock`). Bootstrap with `uv sync --frozen`; add deps with `uv add <pkg>`. `Pulumi.yaml` declares `toolchain: uv` under `runtime.options`, so Pulumi calls `uv` directly on every `preview` / `up` and the lockfile (with its sha256 hashes) is enforced on every provisioning run — not only when a human remembers to `uv sync`. **Never** run `pip install` directly — it bypasses the lockfile and the hash check, which is the whole point of using uv. Prefer `pulumi.Output` composition (`Output.format`, `Output.concat`, `Output.all`) over `.apply()`. `.apply()` callbacks lose Pulumi's secret-redaction flow the moment a value leaves the lambda — it's the most common way secrets leak into logs in a Python-Pulumi project.
- **VPS provider**: DigitalOcean via `pulumi-digitalocean`. Droplets sit in a VPC (`digitalocean.Vpc`) and are attached to a `digitalocean.Firewall` whose `inbound_rule` list is empty — default-deny ingress at the cloud edge, before any OS firewall runs. Outbound rules need only what Tailscale and `apt`/package mirrors require (typically TCP 443 and UDP for NAT traversal). Group resources under a `digitalocean.Project` so the user can audit and tear them down as a unit. Note: DO image slugs like `ubuntu-22-04-x64` are *floating* — they track minor releases. For reproducible bring-up, snapshot a known-good image and pin to its ID.
- **Tailscale auth**: Ephemeral, pre-authorized, single-use, tagged auth keys minted at provision time via the `tailscale.TailnetKey` resource with `ephemeral=True`, `preauthorized=True`, `reusable=False`, `tags=["tag:claude-ops"]`. The key value is a Pulumi secret and is rendered into cloud-init exactly once per `pulumi up`. Single-use means a leaked user-data blob can't re-register the node after first boot; ephemeral means the tailnet object disappears when the droplet shuts down, so destroyed VMs don't accumulate as stale tailnet entries.

## Threat model (read this before changing infra code)

Assume:
- The Pulumi source code is public or could become public. Anything in version control must be safe to publish.
- The DigitalOcean API token, Tailscale OAuth credentials, and any user secrets are sensitive. They live in Pulumi config (encrypted) or Pulumi ESC, never in source.
- DigitalOcean droplet `user_data` is retrievable from the in-droplet metadata service (`169.254.169.254`) and via the DO API by anyone with project read access. Treat user-data as a low-trust transport: it's acceptable for a *single-use, ephemeral, tagged* Tailscale auth key (the threat model assumes that key is consumed on first boot and useless afterwards), but it must not carry reusable credentials, long-lived tokens, or user secrets.
- The droplet is on the public internet during the brief bring-up window before Tailscale comes up. The `digitalocean.Firewall` — not just `ufw` on the box — must default-deny inbound, because the cloud firewall is in effect from the instant the droplet has an IP.
- Claude Code on the VPS has broad shell access by design. The blast radius of a prompt-injection or compromised dependency is the droplet itself, so the droplet must be disposable and isolated from the user's other systems.

## Hard rules

These are non-negotiable. If you find yourself wanting to violate one, stop and ask.

1. **No secrets in source.** No auth keys, API tokens, passwords, private keys, or `.env` contents committed to git. Use `pulumi config set --secret` or Pulumi ESC. Add a pre-commit hook or `.gitignore` entry rather than committing-then-removing.
2. **No public ingress.** The `digitalocean.Firewall` `inbound_rule` list is empty. Tailscale itself needs no inbound — it's outbound-only via DERP / NAT traversal. SSH (port 22) must not be open to `0.0.0.0/0` at the cloud-firewall layer. Access is via Tailscale SSH only.
3. **No `0.0.0.0` listeners for user services.** Anything Claude Code, the user, or helper daemons listen on must bind to the Tailscale interface (`tailscale0`) or `127.0.0.1`, never `0.0.0.0`. Defense-in-depth: the cloud firewall is the primary control, but a misconfigured firewall shouldn't immediately mean a public service.
4. **Tailscale auth keys are ephemeral, single-use, pre-authorized, and tagged** — see *Stack & provider specifics* for the exact `tailscale.TailnetKey` config. Never commit a key, never bake one into a snapshot, never set `reusable=True` "just to debug." A new key is minted on every `pulumi up`.
5. **No `root` SSH, no password SSH.** If SSH is enabled at all, it's key-based, non-root, and reachable only via the tailnet.
6. **Tag every Tailscale node.** Nodes register with a `tag:` (e.g. `tag:claude-ops`). ACLs are written against tags, never against user identities or raw IPs. Untagged nodes inherit the provisioning user's permissions and break the model.
7. **Pulumi state is treated as sensitive.** Use a backend with encryption at rest (Pulumi Cloud or an encrypted self-managed backend with a passphrase / KMS-backed secrets provider). Never commit `.pulumi/` state or stack config with unencrypted secrets.
8. **No interactive prompts in provisioning.** Cloud-init / user-data must be fully unattended. Interactive steps create drift and tempt humans to paste secrets into shell history.
9. **Verify before claiming done.** Before reporting infra work as complete, actually run `pulumi preview` (or `up` on a scratch stack) and confirm the cloud firewall rules, listening ports, and Tailscale ACLs match the intent. Don't infer from the diff alone.

## Strong preferences (override only with explicit user agreement)

- **Idempotent bring-up**: cloud-init must be safe to re-run. No `curl | sh` against unpinned upstream URLs — pin versions and verify checksums or signatures (Tailscale's apt repo with pinned signing key is fine; ad-hoc install scripts are not).
- **Pinned base image**: prefer a `digitalocean.DropletSnapshot` of a known-good image over the floating `ubuntu-22-04-x64` slug. If the floating slug is used, document that as a deliberate trade-off.
- **Unattended security upgrades** enabled on the droplet (`unattended-upgrades`), with automatic reboots scheduled in a window that won't surprise the user.
- **Audit-friendly defaults**: keep `journald` persistent, retain Tailscale logs, and surface a way for the user to inspect them via `tailscale ssh` rather than reading them out via the doc.
- **Disposable, not pet-like**: the droplet should be re-creatable from `pulumi up` with no manual fix-ups. If you find yourself wanting to add a "remember to also run X" note, fold X into the IaC instead.

## Repository conventions

- `infra/` holds the Pulumi Python program. Keep DigitalOcean resources, Tailscale resources, and cloud-init templates in clearly separated modules so an auditor can read networking and secrets policy without grepping through 500 lines of droplet config.
- `cloud-init/` holds user-data templates. Templates are reviewed before each `pulumi up` for accidentally interpolated secrets — DO logs user-data and exposes it via the metadata service, so the only credential allowed in user-data is the single-use Tailscale auth key.
- `pyproject.toml` declares top-level dependencies; `uv.lock` pins every transitive dependency with sha256 hashes — both are committed and both are part of code review (a `uv.lock` diff that touches a Pulumi provider is a supply-chain change, not a noise diff). `Pulumi.<stack>.yaml` may contain encrypted secrets but never plaintext ones. `Pulumi.yaml` itself must be free of environment-specific values.
- Don't add `README` walls of text describing what the code already says. Document **why** decisions were made (especially security trade-offs) in short comments or a `docs/` note.

## Workflow expectations for agents

- **Plan before provisioning.** For any change that alters firewall rules, IAM, ACLs, or secret handling, surface the plan to the user before running `pulumi up`. These are the high-blast-radius changes.
- **Run `pulumi preview` first.** Treat unexpected resource replacements (especially of the VM, network, or Tailscale tailnet objects) as a stop-and-confirm signal — replacement can mean downtime, a new public IP window, or losing in-flight work.
- **Never run `pulumi destroy`, `pulumi stack rm`, force-unlocks, or state edits** without explicit user confirmation for that specific action. "User said yes to destroy yesterday" does not authorize destroying today.
- **Don't paste secrets into the chat or into commit messages.** If you need to show the user a value, redact it (`tskey-auth-…REDACTED`) and tell them where to read it themselves.
- **Don't add new external dependencies casually.** Each new provider, package, or upstream script is supply-chain surface. Justify it.
- **Match scope to the request.** A bug fix in the firewall rule is not an invitation to refactor the whole networking module.

## Verification checklist before declaring infra "done"

Run through this before telling the user a change is shipped:

- [ ] `pulumi preview` shows only the intended diff; no surprise replacements of the droplet, VPC, firewall, or tailnet key.
- [ ] The `digitalocean.Firewall` attached to the droplet has an empty `inbound_rule` list (or only the rules the user explicitly approved).
- [ ] From off-tailnet, the droplet's public IP shows no open ports (e.g. `nmap -Pn <public_ip>` returns no `open` services). Run this from a device that is *not* on the tailnet.
- [ ] On the droplet (via `tailscale ssh`), `ss -tlnp` shows listeners only on `127.0.0.1` or the `tailscale0` interface — never on `0.0.0.0` for user services.
- [ ] `tailscale status` on the droplet shows it tagged `tag:claude-ops`, online, and reachable from the user's device.
- [ ] Tailscale ACLs grant only the intended principals access to `tag:claude-ops` nodes and only on intended ports.
- [ ] No new files contain secrets, auth keys, or tokens (grep for `tskey-`, `dop_v1_`, `ghp_`, `AKIA`, `-----BEGIN`, etc., before committing).
- [ ] `pulumi up` on a fresh stack from a clean checkout succeeds end-to-end with no manual steps, and `pulumi destroy` cleanly removes the droplet, firewall, VPC, project membership, and tailnet key (the ephemeral node entry should disappear from the tailnet on its own).

## When in doubt

Ask. Security defaults are easier to tighten before code lands than to retrofit after a token has leaked or a port has been exposed. A short clarifying question is always cheaper than a rollback.
