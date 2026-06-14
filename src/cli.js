import { autofix } from "./tools/autofix.js";
import { extractAsset } from "./tools/extract-asset.js";
import { extractIcon } from "./tools/extract-icon.js";
import { relabel } from "./tools/relabel.js";
import { scaffoldDiagram } from "./tools/scaffold.js";
import { selectReference } from "./tools/select.js";

export const JS_COMMANDS = new Set(["autofix", "extract-asset", "extract-icon", "relabel", "scaffold", "select"]);

function takeValue(args, index, flag) {
  if (index + 1 >= args.length) {
    throw new Error(`${flag} requires a value`);
  }
  return args[index + 1];
}

function parseCommonOptions(args, spec = {}) {
  const options = {};
  const positionals = [];
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (!arg.startsWith("-")) {
      positionals.push(arg);
      continue;
    }
    switch (arg) {
      case "--json":
        options.json = true;
        break;
      case "--list":
        options.list = true;
        break;
      case "--write":
        options.write = true;
        break;
      case "--dry-run":
        options.dryRun = true;
        break;
      case "--force":
        options.force = true;
        break;
      case "-o":
      case "--out":
      case "--output":
        options.out = takeValue(args, i, arg);
        i += 1;
        break;
      case "--mapping-json":
      case "--mappingJson":
        options.mappingJson = takeValue(args, i, arg);
        i += 1;
        break;
      case "--diagram-name":
        options.diagramName = takeValue(args, i, arg);
        i += 1;
        break;
      case "--template":
      case "--kind":
      case "--id":
      case "--parent":
      case "--label":
        options[arg.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = takeValue(args, i, arg);
        i += 1;
        break;
      case "--top":
      case "--x":
      case "--y":
      case "--w":
      case "--h":
        options[arg.slice(2)] = Number(takeValue(args, i, arg));
        i += 1;
        break;
      case "--include-external-sap-references":
        options.includeExternalSapReferences = true;
        break;
      default:
        if (spec.allowUnknown) {
          positionals.push(arg);
        } else {
          throw new Error(`unknown option: ${arg}`);
        }
    }
  }
  return { options, positionals };
}

export async function runJsCommand(command, args) {
  try {
    if (command === "autofix") {
      const { options, positionals } = parseCommonOptions(args);
      return autofix({ ...options, file: positionals[0] });
    }
    if (command === "extract-icon") {
      const { options, positionals } = parseCommonOptions(args);
      return extractIcon({ ...options, query: positionals.join(" ").trim() });
    }
    if (command === "extract-asset") {
      const { options, positionals } = parseCommonOptions(args);
      return extractAsset({ ...options, query: positionals.join(" ").trim() });
    }
    if (command === "relabel") {
      const { options, positionals } = parseCommonOptions(args);
      return relabel({ ...options, file: positionals[0], mapping: positionals[1] });
    }
    if (command === "select") {
      const { options, positionals } = parseCommonOptions(args);
      return selectReference({ ...options, description: positionals.join(" ").trim() });
    }
    if (command === "scaffold") {
      const { options, positionals } = parseCommonOptions(args);
      return scaffoldDiagram({ ...options, description: positionals.join(" ").trim() });
    }
    return { code: 2, stdout: "", stderr: `unknown JS command: ${command}\n` };
  } catch (error) {
    return { code: 2, stdout: "", stderr: `${error.message}\n` };
  }
}

export function shouldUseJsEngine(command) {
  const engine = (process.env.BTP_DRAWIO_ENGINE || "auto").toLowerCase();
  if (engine === "python") return false;
  if (engine === "js") return true;
  return JS_COMMANDS.has(command);
}
