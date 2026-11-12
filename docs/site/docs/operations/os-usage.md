# OS usage

Ubuntu 24.04 is the shared base platform of the Vergil environment (epic
[vergil-project/.github#649](https://github.com/vergil-project/.github/issues/649)).
This page lists every place an operating system is chosen, the OS, and the
reason. The site docs of other repos link to this page rather than copying it.

Each row is one of two kinds:

- **required**: the OS is fixed by what Vergil ships to. A package target is
  built and install-tested on its own OS, which also sets the glibc floor its
  packages must run on.
- **choice**: the OS is the shared platform. Vergil develops and validates on
  one OS, and 24.04 rather than 26.04 because it supports the current Ubuntu
  LTS and the one before it: working on the older one covers the floor, and
  the package install-tests cover 26.04.

Moving anything to Ubuntu 26.04 is a deliberate change of its own
([vergil-project/.github#651](https://github.com/vergil-project/.github/issues/651)).

## The table

| Where | OS | Kind | Why | Set in |
| ----- | -- | ---- | --- | ------ |
| `pkg-ubuntu:24.04`, the root of the image tree | Ubuntu 24.04 (`ubuntu:24.04`) | required | The 24.04 package target's build and install-test image | `docker/pkg-ubuntu/Dockerfile.template`; the manifest's `toolchains:` |
| `base` | Ubuntu 24.04, from its parent `pkg-ubuntu:24.04` | choice | The shared platform. Building on the package image means packaging needs no Ubuntu 24.04 image outside the tree | The manifest's `base: parent:` |
| `python`, `go`, `rust`, `cpp-clang`, `cpp-gcc`, `ts-node` | Ubuntu 24.04, from their parent `base` | choice | The shared platform. No image builds from a Debian or upstream language image | Each family's `parent:` in the manifest |
| `pkg-ubuntu:26.04` | Ubuntu 26.04 (`ubuntu:26.04`) | required | The 26.04 package target's build and install-test image | `docker/pkg-ubuntu/Dockerfile.template`; the manifest's `toolchains:` |
| `pkg-rhel:9`, `pkg-rhel:10` | RHEL 9 and 10 (UBI, `registry.access.redhat.com/ubi<version>/ubi`) | required | The RHEL package targets' build and install-test images | `docker/pkg-rhel/Dockerfile.template`; the manifest's `toolchains:` |
| Local agent VMs (Lima) | Ubuntu 24.04 (`template:_images/ubuntu-24.04`) | choice | The shared platform, pinned rather than the floating `template:_images/ubuntu-lts`, which moves to each new LTS | vergil-vm `templates/agent.yaml.skel` |
| Cloud agent VMs (Azure) | Ubuntu 24.04 (Canonical `ubuntu-24_04-lts`) | choice | The shared platform | vergil-vm `opentofu/modules/azure/vm/main.tf` |
| Cloud agent VMs (GCP) | Ubuntu 24.04 (`ubuntu-os-cloud/ubuntu-2404-lts-amd64`) | choice | The shared platform | vergil-vm `opentofu/modules/gcp/vm/main.tf` |
| GitHub-hosted runners | Ubuntu 24.04: `ubuntu-24.04` (amd64), `ubuntu-24.04-arm` (arm64) | choice | The shared platform. `ubuntu-latest` floats, and ran Ubuntu 26.04 for Vergil's jobs from early November 2026, so workflows name the release | Each repo's `.github/workflows/` |

The image tree is the same under both prefixes: each `dev-` image is built on
its `dev-` parent, and each `prod-` image on its `prod-` parent. The `pkg-`
images outside the tree carry only what a package job needs (see
[Images](../images/index.md#package-toolchain-images)), so an install-test
still proves an install on a clean target.

## Where the move stands

As of 2026-11-11, the table is the design that `develop` builds, and these
parts are still moving to it:

- **`prod-` images.** vergil-containers releases nothing from the rebase of
  `base` until the cutover release
  ([vergil-containers#789](https://github.com/vergil-project/vergil-containers/issues/789)),
  so the released `prod-` language images and `prod-base` are still built from
  the last release's Debian templates. The `dev-` images, published from
  `develop`, are on the tree above.
- **Lima VMs.** The template is pinned to 24.04
  ([vergil-vm#394](https://github.com/vergil-project/vergil-vm/issues/394)).
  An existing VM moves with `vrg-vm rebuild` after the vergil-vm release that
  carries the pin
  ([vergil-vm#395](https://github.com/vergil-project/vergil-vm/issues/395));
  `vrg-vm update` does not change the OS.
- **Runner labels.** In vergil-containers, the image build legs run on
  `ubuntu-24.04` and `ubuntu-24.04-arm`, and every other job runs on
  `ubuntu-24.04`
  ([vergil-containers#776](https://github.com/vergil-project/vergil-containers/issues/776)).
  Once every repo names the release, a check in vergil-tooling's validation
  refuses `ubuntu-latest` in a workflow
  ([vergil-tooling#4129](https://github.com/vergil-project/vergil-tooling/issues/4129)).
