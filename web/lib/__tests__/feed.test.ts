import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { SyloEvent } from "../events";
import { describe as describeEvent, outcomeBadge } from "../feed";

function fixture(name: string): SyloEvent[] {
  const contents = readFileSync(
    new URL(`../../samples/fixtures/${name}.jsonl`, import.meta.url),
    "utf8",
  );
  return contents
    .trim()
    .split(/\r?\n/)
    .map((line) => JSON.parse(line) as SyloEvent);
}

function first(name: string, type: string): SyloEvent {
  const event = fixture(name).find((candidate) => candidate.type === type);
  if (!event) throw new Error(`${type} missing from ${name}`);
  return event;
}

function event(type: string, data: Record<string, unknown>): SyloEvent {
  return {
    v: 1,
    seq: 1,
    id: "evt-000001",
    ts: "2026-10-11T09:00:00.000Z",
    type,
    paymentId: "PAY-TEST",
    simulated: true,
    data,
  } as unknown as SyloEvent;
}

describe("feed outcome", () => {
  it("takes the verification outcome from data.result, not the answer text", () => {
    expect(describeEvent(first("scene2-confirm", "verification.recorded")).outcome).toBe("CONFIRMED");
    expect(describeEvent(first("scene2-deny", "verification.recorded")).outcome).toBe("DENIED");

    const misleading = describeEvent(
      event("verification.recorded", { result: "DENIED", answerText: "Yes, this is our new account." }),
    );
    expect(outcomeBadge(misleading)).toEqual({ label: "Denied", tone: "danger" });
  });

  it("takes the risk outcome from data.tier", () => {
    expect(describeEvent(first("scene1-legit", "risk.scored")).outcome).toBe("LOW");
    const diverted = first("scene2-diverted", "risk.scored");
    expect(describeEvent(diverted).outcome).toBe((diverted.data as { tier: string }).tier);
    expect(describeEvent(diverted).outcome).not.toBe("LOW");
  });

  it("maps verification outcomes to badges", () => {
    const type = "verification.recorded";
    expect(outcomeBadge({ type, outcome: "CONFIRMED" })).toEqual({ label: "Confirmed", tone: "success" });
    expect(outcomeBadge({ type, outcome: "DENIED" })).toEqual({ label: "Denied", tone: "danger" });
    expect(outcomeBadge({ type })).toEqual({ label: "Recorded", tone: "neutral" });
  });

  it("maps risk tiers to badges", () => {
    const type = "risk.scored";
    expect(outcomeBadge({ type, outcome: "LOW" })).toEqual({ label: "Low risk", tone: "success" });
    expect(outcomeBadge({ type, outcome: "MEDIUM" })).toEqual({ label: "Medium risk", tone: "warning" });
    expect(outcomeBadge({ type, outcome: "HIGH" })).toEqual({ label: "High risk", tone: "warning" });
    expect(outcomeBadge({ type, outcome: "CRITICAL" })).toEqual({ label: "Critical", tone: "danger" });
    expect(outcomeBadge({ type })).toEqual({ label: "Scored", tone: "neutral" });
  });

  it("leaves other events without an outcome badge", () => {
    const item = describeEvent(event("route.selected", { name: "R1", etaLabel: "2 h" }));
    expect(item.outcome).toBeUndefined();
    expect(outcomeBadge(item)).toBeNull();
  });

  it("labels detector clusters with singular and plural counts", () => {
    expect(
      describeEvent(
        event("cluster.detected", {
          detector: "networkx-mule-clusters",
          clusterId: "cluster-one",
          regionName: "Volta Region",
          accounts: 1,
          linkedPayments: ["P1"],
        }),
      ).text,
    ).toBe("Mule cluster cluster-one · Volta Region · 1 account · 1 payment");

    expect(
      describeEvent(
        event("cluster.detected", {
          detector: "networkx-mule-clusters",
          clusterId: "cluster-many",
          region: "Volta",
          accounts: 2,
          linkedPayments: ["P1", "P2"],
          agents: 2,
        }),
      ).text,
    ).toBe("Mule cluster cluster-many · Volta · 2 accounts · 2 payments · 2 agents");
  });

  it("preserves sample-cluster wording and singularizes account and agent counts", () => {
    expect(
      describeEvent(
        event("cluster.detected", {
          detector: "cluster-sample",
          clusterId: "CL-AFLAO-01",
          accounts: 1,
          agents: 1,
        }),
      ).text,
    ).toBe("Sample cluster CL-AFLAO-01 · 1 account · 1 agent");

    expect(
      describeEvent(
        event("cluster.detected", {
          detector: "cluster-sample",
          clusterId: "CL-AFLAO-02",
          accounts: 2,
          agents: 0,
        }),
      ).text,
    ).toBe("Sample cluster CL-AFLAO-02 · 2 accounts · 0 agents");
  });

  it("omits missing detector payment counts and labels every new scene event", () => {
    expect(
      describeEvent(
        event("cluster.detected", {
          detector: "networkx-mule-clusters",
          clusterId: "cluster-fallback",
          region: "Volta",
          accounts: 1,
        }),
      ).text,
    ).toBe("Mule cluster cluster-fallback · Volta · 1 account");

    for (const name of [
      "scene2-simswap",
      "samples-hold-expiry",
      "samples-time-lock",
      "samples-confidential",
    ]) {
      const labels = fixture(name).map((sceneEvent) => describeEvent(sceneEvent).text);
      expect(labels.every((label) => !label.startsWith("Event received:"))).toBe(true);
    }
  });
});
