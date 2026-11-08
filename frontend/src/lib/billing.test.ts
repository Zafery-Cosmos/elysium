import { describe, expect, it } from "vitest";
import { groupByBilling, providerBilling } from "./billing";
import type { ProviderInfo } from "../types/engine";

const P = (p: Partial<ProviderInfo> & { name: string }): ProviderInfo => ({ configured: true, ...p });

describe("providerBilling", () => {
  it("treats CLI providers as subscription (OAuth)", () => {
    expect(providerBilling(P({ name: "claude-code", kind: "cli" }))).toBe("subscription");
    expect(providerBilling(P({ name: "codex", kind: "cli" }))).toBe("subscription");
  });

  it("treats key-based cloud providers as API", () => {
    expect(providerBilling(P({ name: "anthropic", kind: "anthropic" }))).toBe("api");
    expect(providerBilling(P({ name: "openrouter", kind: "openai" }))).toBe("api");
    expect(providerBilling(P({ name: "my-custom-server", kind: "openai" }))).toBe("api");
  });

  it("recognises local providers by flag, kind or well-known name", () => {
    expect(providerBilling(P({ name: "x", is_local: true }))).toBe("local");
    expect(providerBilling(P({ name: "x", kind: "local" }))).toBe("local");
    expect(providerBilling(P({ name: "ollama" }))).toBe("local");
    expect(providerBilling(P({ name: "lmstudio" }))).toBe("local");
  });
});

describe("groupByBilling", () => {
  const providers = [
    P({ name: "openai", kind: "openai" }),
    P({ name: "ollama", kind: "openai", is_local: true }),
    P({ name: "codex", kind: "cli", configured: false }),
    P({ name: "anthropic", kind: "anthropic", configured: false }),
    P({ name: "claude-code", kind: "cli" }),
    P({ name: "xai", kind: "openai" }),
  ];

  it("orders groups subscription, then API, then local", () => {
    expect(groupByBilling(providers).map((g) => g.billing)).toEqual(["subscription", "api", "local"]);
  });

  it("puts configured providers first inside a group and keeps the original order otherwise", () => {
    const groups = groupByBilling(providers);
    expect(groups[0]?.providers.map((p) => p.name)).toEqual(["claude-code", "codex"]);
    expect(groups[1]?.providers.map((p) => p.name)).toEqual(["openai", "xai", "anthropic"]);
  });

  it("omits empty groups and does not mutate its input", () => {
    const only = [P({ name: "openai", kind: "openai" })];
    expect(groupByBilling(only).map((g) => g.billing)).toEqual(["api"]);
    const copy = [...providers];
    groupByBilling(providers);
    expect(providers).toEqual(copy);
  });
});
