import { copyFile } from "node:fs/promises";
for (const name of [
  "robotics-workflow.js",
  "robotics-workflow.d.ts",
  "robotics-import.js",
  "robotics-import.d.ts",
]) {
  await copyFile(
    new URL(`../sdk-node/lib/${name}`, import.meta.url),
    new URL(`../web/lib/${name}`, import.meta.url),
  );
}
