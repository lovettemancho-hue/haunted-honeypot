/**
 * Config tests for deploy/docker-compose.yml, deploy/Caddyfile and the built dist/.
 * Validates: Requirements 10.2, 10.3, 11.2, 11.4, 11.5, 12.2, 12.3, 12.4, 12.6, 12.7
 */
// @vitest-environment node
import { execSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { parse } from "yaml";
import { beforeAll, describe, expect, it } from "vitest";

const dashboardDir = resolve(__dirname, "..");
const repoRoot = resolve(dashboardDir, "..");

interface Service {
  ports?: string[];
  networks?: string[];
  volumes?: string[];
  read_only?: boolean;
  cap_drop?: string[];
  security_opt?: string[];
  mem_limit?: string;
  cpus?: string;
  restart?: string;
  build?: { context: string; dockerfile: string };
  image?: string;
  env_file?: string[];
}
interface Compose {
  services: Record<string, Service>;
  volumes: Record<string, unknown>;
  networks: Record<string, unknown>;
}

const compose = parse(
  readFileSync(join(repoRoot, "deploy", "docker-compose.yml"), "utf8"),
) as Compose;
const caddyfile = readFileSync(join(repoRoot, "deploy", "Caddyfile"), "utf8");

describe("docker-compose.yml", () => {
  it("leaves the trap service unchanged", () => {
    const trap = compose.services.trap;
    expect(trap.build).toEqual({ context: "..", dockerfile: "trap/Dockerfile" });
    expect(trap.image).toBe("haunted-trap:latest");
    expect(trap.read_only).toBe(true);
    expect(trap.cap_drop).toEqual(["ALL"]);
    expect(trap.security_opt).toEqual(["no-new-privileges:true"]);
    expect(trap.mem_limit).toBe("256m");
    expect(trap.cpus).toBe("0.5");
    expect(trap.volumes).toEqual(["trap_keys:/data/keys", "trap_logs:/data/logs"]);
    expect(trap.ports).toEqual(["${TRAP_PUBLIC_PORT:-22}:2222"]);
    expect(trap.networks).toEqual(["trap_net"]);
  });

  it("keeps the trap off every network used by the new services", () => {
    const trapNets = new Set(compose.services.trap.networks);
    for (const name of ["dashboard", "caddy", "brain"]) {
      for (const net of compose.services[name].networks ?? []) {
        expect(trapNets.has(net), `${name} shares ${net} with trap`).toBe(false);
      }
    }
    expect(compose.services.dashboard.networks?.length).toBeGreaterThan(0);
    expect(compose.services.caddy.networks?.length).toBeGreaterThan(0);
  });

  it("does not let the trap mount any volume used by the new services", () => {
    const vol = (s: Service) => (s.volumes ?? []).map((v) => v.split(":")[0]);
    const trapVols = new Set(vol(compose.services.trap));
    for (const name of ["dashboard", "caddy"]) {
      for (const v of vol(compose.services[name])) {
        if (v.startsWith(".")) continue;
        expect(trapVols.has(v)).toBe(false);
      }
    }
  });

  it("publishes ports only on trap (SSH) and caddy (80/443)", () => {
    const published = Object.entries(compose.services)
      .filter(([, s]) => (s.ports ?? []).length > 0)
      .map(([n]) => n)
      .sort();
    expect(published).toEqual(["caddy", "trap"]);
    expect(compose.services.caddy.ports).toEqual(["80:80", "443:443"]);
    expect(compose.services.dashboard.ports).toBeUndefined();
    expect(compose.services.brain.ports).toBeUndefined();
  });

  it("gives caddy and dashboard no-new-privileges and a restart policy", () => {
    for (const name of ["caddy", "dashboard"]) {
      expect(compose.services[name].security_opt).toContain("no-new-privileges:true");
      expect(compose.services[name].restart).toBe("unless-stopped");
    }
  });

  it("attaches caddy to the brain network", () => {
    const brainNets = compose.services.brain.networks ?? [];
    const shared = (compose.services.caddy.networks ?? []).filter((n) =>
      brainNets.includes(n),
    );
    expect(shared.length).toBeGreaterThan(0);
  });

  it("stores caddy certificate data in a named volume", () => {
    const mount = (compose.services.caddy.volumes ?? []).find((v) => v.endsWith(":/data"));
    expect(mount).toBeDefined();
    const name = mount!.split(":")[0];
    expect(name.startsWith(".") || name.startsWith("/")).toBe(false);
    expect(Object.keys(compose.volumes)).toContain(name);
  });
});

describe("Caddyfile", () => {
  it("uses {$DOMAIN::80} as the site address (plain :80 fallback)", () => {
    expect(caddyfile).toMatch(/^\{\$DOMAIN::80\}\s*\{/m);
  });

  it("proxies /api/* to brain:8000", () => {
    expect(caddyfile).toMatch(/handle\s+\/api\/\*\s*\{[^}]*reverse_proxy\s+brain:8000/);
  });

  it("falls back to index.html for SPA routes and serves /srv", () => {
    expect(caddyfile).toMatch(/try_files\s+\{path\}\s+\/index\.html/);
    expect(caddyfile).toMatch(/root\s+\*\s+\/srv/);
    expect(caddyfile).toMatch(/file_server/);
  });
});

function listFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const p = join(dir, entry);
    return statSync(p).isDirectory() ? listFiles(p) : [p];
  });
}

function envValues(file: string): string[] {
  if (!existsSync(file)) return [];
  return readFileSync(file, "utf8")
    .split(/\r?\n/)
    .map((l) => l.trim().replace(/^#\s*/, ""))
    .map((l) => /^[A-Z][A-Z0-9_]*(TOKEN|KEY|SECRET|PASSWORD)[A-Z0-9_]*=(.+)$/.exec(l))
    .filter((m): m is RegExpExecArray => m !== null)
    .map((m) => m[2].trim().replace(/^["']|["']$/g, ""))
    .filter((v) => v.length >= 6);
}

describe("built dist/", () => {
  beforeAll(() => {
    execSync("npm run build", { cwd: dashboardDir, stdio: "pipe" });
  }, 170_000);

  it("exists with an index.html", () => {
    expect(existsSync(join(dashboardDir, "dist", "index.html"))).toBe(true);
  });

  it("contains no token or secret values", () => {
    const secrets = [
      ...envValues(join(repoRoot, ".env")),
      ...envValues(join(repoRoot, ".env.example")),
    ];
    const patterns = [/BRAIN_API_TOKEN/, /BRAIN_LLM_API_KEY/, /TRAP_LLM_API_KEY/, /AIza[0-9A-Za-z_-]{30,}/, /sk-[A-Za-z0-9]{20,}/];
    const files = listFiles(join(dashboardDir, "dist"));
    expect(files.length).toBeGreaterThan(0);
    for (const f of files) {
      const text = readFileSync(f, "utf8");
      for (const s of secrets) expect(text.includes(s), `${f} contains secret value`).toBe(false);
      for (const p of patterns) expect(p.test(text), `${f} matches ${p}`).toBe(false);
    }
  });
});
