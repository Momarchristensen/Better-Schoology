/** @type {import("stylelint").Config} */
module.exports = {
  defaultSeverity: "warning",
  extends: ["stylelint-config-standard"],
  customSyntax: "postcss-html",
  rules: {
    "declaration-block-no-duplicate-properties": true,
    "declaration-block-no-shorthand-property-overrides": true,
    "no-descending-specificity": true,
    "selector-no-qualifying-type": null,
    "selector-class-pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*(?:--[a-z0-9]+(?:-[a-z0-9]+)*)?$",
    "property-no-vendor-prefix": true,
    "value-no-vendor-prefix": true,
    "font-family-no-missing-generic-family-keyword": true,
    "color-function-alias-notation": "without-alpha",
    "color-function-notation": "modern",
    "declaration-property-value-keyword-no-deprecated": null,
    "rule-empty-line-before": null
  },
};

//Install Command: npm i -D stylelint stylelint-config-standard postcss-html