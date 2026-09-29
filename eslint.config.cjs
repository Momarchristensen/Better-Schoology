/** @type {import("eslint").FlatConfig[]} */
const stylistic = require("@stylistic/eslint-plugin")
const globals = require("globals")
const html = require("eslint-plugin-html")

module.exports = [
  {
    files: ["web/**/*.js", "web/**/*.html"],
    plugins: {
      "@stylistic": stylistic,
      html,
    },
    languageOptions: {
      globals: {
        ...globals.browser,
        console: "readonly",
        DEFAULT_SETTINGS: "readonly",
        DOMPurify: "readonly",
        EasyMDE: "readonly",
        eval: "readonly",
        fetchWithRetry: "readonly",
        gapi: "readonly",
        getStoredSetting: "readonly",
        google: "readonly",
        marked: "readonly",
        Quill: "readonly",
        SETTINGS_KEYS: "readonly",
      },
      parserOptions: {
        ecmaVersion: 2022,
        sourceType: "module",
      },
    },
    rules: {
      "no-extra-parens": ["warn", "all"],
      "no-undef": "warn",
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      curly: "warn",
      quotes: ["warn", "double"],
      "no-dupe-keys": "warn",
      "consistent-return": "warn",
      "no-else-return": "warn",
      "no-unneeded-ternary": "warn",
      "no-duplicate-imports": "warn",
      semi: ["warn", "never"],
      "no-throw-literal": "warn",
      "no-unmodified-loop-condition": "warn",
      "no-unsafe-negation": "warn",
      "prefer-spread": "warn",
      "no-new-func": "warn",
      "array-callback-return": "warn",
      "no-useless-call": "warn",
      "@stylistic/operator-linebreak": ["warn", "none"],
      "@stylistic/brace-style": ["warn", "stroustrup", { allowSingleLine: false }],
    },
  },
]
//Install Command: npm install --save-dev eslint @stylistic/eslint-plugin globals eslint-plugin-html