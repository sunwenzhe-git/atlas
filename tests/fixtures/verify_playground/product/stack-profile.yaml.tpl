product: verify-playground
apps:
  - name: app
    path: .
    kind: frontend
    role: landing
    stack: static
prototype:
  dir: product/prototype
  base_url: http://127.0.0.1:{PORT}
e2e:
  runner: node-playwright
  cases_dir: product/e2e/cases
  index: product/e2e/e2e-index.md
  scripts_dir: product/e2e/scripts
  app_base_url: http://127.0.0.1:{PORT}
  app_login:
    mode: none
