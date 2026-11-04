esbuild 0.25.5 (https://esbuild.github.io/, MIT licence in LICENSE.md), the
statically linked linux-x64 binary of the npm package @esbuild/linux-x64.
sha256 3331e0b23c99d93d9a39e436a4838de40ca1c95ac3bcbd9874ba169d8545b634

tools/build_release.py (TASK-893) runs it offline to whitespace-minify the
game scripts of a release bundle: --minify-whitespace only, so no identifier
is renamed and no syntax is rewritten (classic scripts share globals;
function names stay). ESBUILD=/path/to/esbuild overrides the binary.
