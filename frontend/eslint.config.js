import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import vueParser from 'vue-eslint-parser'
import tseslint from 'typescript-eslint'
import prettierConfig from 'eslint-config-prettier'

export default [
  {
    // Global ignores
    ignores: [
      'dist/**',
      'node_modules/**',
      'src/picframe/html/**',
      '*.config.*',
      // Ad-hoc Node scripts at the frontend root (not part of the SPA bundle)
      'test_*.js',
    ],
  },

  // Base JS recommended
  js.configs.recommended,

  // Vue 3 recommended rules (does not set the parser in v10 — see block below)
  ...vue.configs['flat/recommended'],

  // TypeScript recommended for .ts/.tsx files
  ...tseslint.configs.recommended,

  // Parse .vue files with vue-eslint-parser, and use the TS parser
  // for <script lang="ts"> blocks.
  {
    files: ['**/*.vue'],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
      },
    },
  },

  // Project-specific rules
  {
    rules: {
      // Block debug logging (console.log / debug / info) but allow
      // console.warn and console.error for legitimate error reporting.
      // This is the rule that would have caught the stray debug console.log
      // statements removed in #736.
      'no-console': ['error', { allow: ['warn', 'error'] }],
      // TypeScript (via vue-tsc) already checks for undefined variables, and
      // `no-undef` doesn't understand DOM/browser globals in .vue files.
      'no-undef': 'off',
      // Allow unused caught errors (catch (e) where e is not referenced);
      // optional-catch-binding could replace these, but avoid the churn.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { caughtErrors: 'none', argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // Single-word view names are intentional (RemoteView, SettingsView, etc.)
      'vue/multi-word-component-names': 'off',
      // Allow v-html in controlled contexts (i18n / trusted content)
      'vue/no-v-html': 'off',
      // Establish a baseline without a large `any`-type refactor; surface
      // them as warnings for future cleanup rather than blocking CI.
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },

  // Disable formatting rules that conflict with Prettier (must be last)
  prettierConfig,
]
