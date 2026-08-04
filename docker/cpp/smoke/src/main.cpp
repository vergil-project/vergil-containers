#include <fmt/core.h>

// Trivial CMake + Conan 2 smoke program: exercises dependency resolution
// (Conan pulls fmt), compilation, linking against a compiled library, and
// running under the image's default compiler. See docker/cpp/smoke-test.sh.
int main() {
  fmt::print("cpp smoke ok: {}\n", 6 * 7);
  return 0;
}
