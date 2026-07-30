import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  {
    ignores: [
      'dist',
      // QZ Tray signing key placeholder. It is deliberately NOT valid
      // TypeScript (the real key is injected per-deployment and is never
      // committed), so linting it only ever produces a parse error.
      'src/privateKey.ts',
    ],
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      // Honour the `_` prefix as "intentionally unused". Without this
      // there is no way to keep a binding that MUST exist for signature
      // reasons — a zustand slice's `(set, get)`, a prop that's part of a
      // component's public API, a positional callback arg — and the code
      // already used `_email` / `_result` expecting it to work. Those
      // were still being flagged, which is what makes the rule feel
      // arbitrary and trains people to ignore it.
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
          destructuredArrayIgnorePattern: '^_',
        },
      ],
    },
  },
)
