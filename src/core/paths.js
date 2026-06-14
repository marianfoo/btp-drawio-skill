import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

export const packageRoot = resolve(here, "..", "..");
export const skillRoot = join(packageRoot, "plugins", "sap-architecture", "skills", "sap-architecture");
export const assetsDir = join(skillRoot, "assets");
export const referenceExamplesDir = join(assetsDir, "reference-examples");
export const librariesDir = join(assetsDir, "libraries");
export const iconIndexPath = join(assetsDir, "icon-index.json");
export const assetIndexPath = join(assetsDir, "asset-index.json");
