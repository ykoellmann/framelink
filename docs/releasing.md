# Releasing

Everything is built by GitHub Actions (`.github/workflows/`). A release is a Git tag.

## Cut a release

```bash
git tag v1.2.3
git push origin v1.2.3
```

A tag like `v1.2.3-rc1` is a pre-release: it is published but does not become "latest", so the one-line installer and `framelink-update` keep using the previous release.

## What happens

| Workflow | Trigger | Result |
|---|---|---|
| `ci.yml` | pull requests (and called by `docker.yml`) | `pytest` for registry and frame (Python 3.11 and 3.12), Docker build and smoke test of both images (amd64) |
| `docker.yml` | push to `main`, tags `v*` | after the tests pass, builds and pushes `ghcr.io/<owner>/framelink-registry` and `ghcr.io/<owner>/framelink-frame` for amd64 and arm64. Tags: `latest` (from `main`), `1.2.3` and `1.2` (from a tag), `sha-<commit>` |
| `release.yml` | tags `v*` | sets the version from the tag, builds the frame wheel (fonts included), creates a GitHub release with the assets below |

Release assets (the installer downloads exactly these names):

- `install.sh`: the one-line installer, `curl -fsSL https://github.com/<owner>/framelink/releases/latest/download/install.sh | sudo bash`
- `framelink-frame.tar.gz`: `framelink-frame/` with `install.sh`, `systemd/`, `config.yaml.example` and the wheel
- `framelink_frame-<version>-py3-none-any.whl`

The version in `registry/pyproject.toml` and `frame/pyproject.toml` stays `0.1.0` in the repository. The release workflow replaces it from the tag in its own checkout only.

## First time only

1. Push to GitHub and make the repository public.
2. After the first successful `docker.yml` run, check the visibility of the two packages (`framelink-registry`, `framelink-frame`): the repository's **Packages** → the package → **Package settings**. With a public repository they were public from the start (the images carry the `org.opencontainers.image.source` label that links them to it). If one is private, use **Change visibility** → **Public**; a workflow cannot do that. A quick test without any login: `docker pull ghcr.io/<owner>/framelink-registry:latest`.
3. Check that **Settings → Actions → General → Workflow permissions** allows the workflows to create releases (the workflow asks for `contents: write` itself).

## Checking a release

- `docker pull ghcr.io/<owner>/framelink-registry:1.2.3` works without login. The images contain `linux/amd64` and `linux/arm64`.
- On a Pi: `curl … | sudo bash` and `sudo framelink-update v1.2.3`.
- The installer can be tested without GitHub: build a release folder layout (`latest/download/{install.sh,framelink-frame.tar.gz}`) and run `FRAMELINK_RELEASE_BASE=file:///path bash install.sh --no-systemd --no-cec` in a `debian:bookworm-slim` container.
