import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dashboardDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectDir = path.resolve(dashboardDir, "..");
const database = path.join(projectDir, "rpg_bot.db");
const vinext = path.join(
  dashboardDir,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "vinext.cmd" : "vinext",
);

const pythonCandidates = [
  process.env.VIRTUAL_ENV
    ? path.join(
        process.env.VIRTUAL_ENV,
        process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
      )
    : null,
  path.join(
    projectDir,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  ),
].filter(Boolean);

const python = pythonCandidates.find((candidate) => {
  if (!existsSync(candidate)) return false;
  const check = spawnSync(candidate, ["-c", "import discord, PIL"], {
    cwd: projectDir,
    stdio: "ignore",
  });
  return check.status === 0;
});

if (!python) {
  console.error("Ingen fungerande .venv med projektets Python-paket hittades.");
  console.error("Aktivera .venv och kör: python -m pip install -r requirements.txt");
  process.exit(1);
}
if (!existsSync(vinext)) {
  console.error(`Dashboard-paketen saknas: ${vinext}`);
  console.error("Kör: npm --prefix dashboard install");
  process.exit(1);
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

function openDashboard() {
  const url = "http://localhost:3000";
  if (process.env.NO_BROWSER === "1") return;
  const commands = {
    win32: ["cmd", ["/c", "start", "", url]],
    darwin: ["open", [url]],
    linux: ["xdg-open", [url]],
  };
  const selected = commands[process.platform];
  if (!selected) return;
  const browser = spawn(selected[0], selected[1], {
    detached: true,
    stdio: "ignore",
  });
  browser.unref();
}

async function openDashboardWhenReady() {
  for (let attempt = 0; attempt < 60 && !stopping; attempt += 1) {
    if (await isPortOpen(3000)) {
      openDashboard();
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  console.error("Dashboarden blev inte tillgänglig på http://localhost:3000.");
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

const bot = start(python, ["-m", "rpg_bot"], projectDir);
const api = apiAlreadyRunning
  ? null
  : start(python, ["-m", "rpg_bot.dashboard_server", "--database", database], projectDir);
const ui = uiAlreadyRunning
  ? null
  : start(vinext, ["dev"], dashboardDir, process.platform === "win32");

if (apiAlreadyRunning) console.log("Dashboard-API:t kör redan på http://localhost:8765");
if (uiAlreadyRunning) console.log("Dashboarden kör redan på http://localhost:3000");
void openDashboardWhenReady();

bot.on("exit", (code) => {
  if (!stopping) {
    console.error(`Discord-botten avslutades (kod ${code ?? "okänd"}).`);
    stop(code ?? 1);
  }
});

api?.on("exit", (code) => {
  if (!stopping) {
    console.error(`Dashboard-API:t avslutades (kod ${code ?? "okänd"}).`);
    stop(code ?? 1);
  }
});

ui?.on("exit", (code) => {
  if (!stopping) {
    console.error(`Dashboarden avslutades (kod ${code ?? "okänd"}).`);
    stop(code ?? 1);
  }
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => stop(0));
}
