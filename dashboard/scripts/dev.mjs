import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dashboardDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectDir = path.resolve(dashboardDir, "..");
const python = path.join(projectDir, ".runtime", "python312", "tools", "python.exe");
const apiBootstrap = path.join(projectDir, "scripts", "dashboard_api_bootstrap.py");
const database = path.join(projectDir, "rpg_bot.db");
const vinext = path.join(
  dashboardDir,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "vinext.cmd" : "vinext",
);

for (const [label, executable] of [
  ["Python runtime", python],
  ["vinext", vinext],
]) {
  if (!existsSync(executable)) {
    console.error(`${label} saknas: ${executable}`);
    console.error("Kör projektets installationssteg och försök igen.");
    process.exit(1);
  }
}

const children = [];
let stopping = false;

function isPortOpen(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: "localhost", port });
    socket.setTimeout(300);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("timeout", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", () => resolve(false));
  });
}

function start(command, args, cwd, shell = false) {
  const child = spawn(command, args, { cwd, shell, stdio: "inherit" });
  children.push(child);
  return child;
}

function stop(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode === null) child.kill();
  }
  process.exitCode = exitCode;
}

const apiAlreadyRunning = await isPortOpen(8765);
const uiAlreadyRunning = await isPortOpen(3000);

const api = apiAlreadyRunning
  ? null
  : start(
      python,
      [apiBootstrap, "--database", database],
      projectDir,
    );
const ui = uiAlreadyRunning
  ? null
  : start(vinext, ["dev"], dashboardDir, process.platform === "win32");

if (apiAlreadyRunning) console.log("Dashboard-API:t kör redan på http://localhost:8765");
if (uiAlreadyRunning) console.log("Dashboarden kör redan på http://localhost:3000");
if (apiAlreadyRunning && uiAlreadyRunning) process.exit(0);

api?.on("exit", (code) => {
  if (!stopping) {
    console.error(`Dashboard-API:t avslutades (kod ${code ?? "okänd"}).`);
    stop(code ?? 1);
  }
});

ui?.on("exit", (code) => {
  if (!stopping) stop(code ?? 0);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => stop(0));
}
