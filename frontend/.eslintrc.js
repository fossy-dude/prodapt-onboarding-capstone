export default [
  {
    ignores: ["node_modules/", "dist/", "build/", ".vite/"],
  },
  {
    files: ["src/**/*.{js,jsx,ts,tsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
      globals: {
        console: "readonly",
        process: "readonly",
      },
    },
    rules: {
      // Strict mode
      "no-var": "error",
      "prefer-const": "error",

      // Best practices
      "no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      "no-console": ["warn", { allow: ["warn", "error"] }],
      eqeqeq: ["error", "always"],
      curly: "error",
      "no-implicit-coercion": "error",
      "no-eval": "error",

      // Style
      semi: ["error", "always"],
      quotes: ["error", "double", { avoidEscape: true }],
      indent: ["error", 2],
      "comma-dangle": ["error", "always-multiline"],
      "no-trailing-spaces": "error",
      "eol-last": ["error", "always"],
    },
  },
];
