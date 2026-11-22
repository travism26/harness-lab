import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["node_modules/"] },
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    files: ["**/*.js", "**/*.mjs"],
    languageOptions: { globals: globals.node },
  },
);
