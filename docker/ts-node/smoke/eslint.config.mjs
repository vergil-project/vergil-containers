// ESLint flat config for the ts-node smoke project: the config ESLint needs to
// run at all. It uses the rule sets of Vergil's managed base (vergil-tooling's
// configs/typescript/eslint.config.mjs): @eslint/js's recommended rules and
// typescript-eslint's type-aware recommendedTypeChecked. Both imports resolve
// from the project's node_modules, which hold the tools the project declares;
// the image carries none of them (vergil-tooling's tool-ownership guideline,
// epic vergil-project/.github#1174).

import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["coverage/", "node_modules/"],
  },
  {
    files: ["**/*.ts"],
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: true,
      },
    },
  },
);
