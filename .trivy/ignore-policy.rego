# Trivy ignore policy: categorically drop linux-libc-dev (kernel header)
# findings. Dev containers use the HOST kernel at runtime, not the kernel
# headers baked into the base image, so every linux-libc-dev CVE is a false
# positive for this image set — including the occasional one that carries a
# Debian fix (which `ignore-unfixed` alone would not catch). Evaluated against
# each vulnerability; returning true suppresses it from the gate and report.
package trivy

import rego.v1

default ignore := false

ignore if {
	input.PkgName == "linux-libc-dev"
}
