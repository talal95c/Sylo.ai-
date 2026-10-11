"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { SyloEvent } from "./events";
import {
  availableActions,
  closeAlert,
  initialState,
  reduce,
  resetForSourceChange,
  type ViewState,
} from "./store";
import {
  createLiveSource,
  createReplaySource,
  type AttackName,
  type ScenarioName,
  type Source,
  type SourceKind,
} from "./source";
import { engineConnectTimeoutMs, engineUrl } from "./engine";

type UiAction = { type: "ui.closeAlert" } | { type: "ui.sourceChanged" };
type HookAction = SyloEvent | UiAction;

function hookReducer(state: ViewState, action: HookAction): ViewState {
  if (!("v" in action)) {
    if (action.type === "ui.closeAlert") return closeAlert(state);
    return resetForSourceChange(state);
  }
  return reduce(state, action);
}

const offlineNotice = "Engine offline: replaying recorded events";

export function useSylo() {
  const [state, dispatch] = useReducer(hookReducer, initialState);
  const [sourceKind, setSourceKindState] = useState<SourceKind>(
    process.env.NEXT_PUBLIC_SOURCE === "replay" ? "replay" : "live",
  );
  const [notice, setNotice] = useState<string>();
  const [speed, setSpeedState] = useState<1 | 2>(1);
  const [toasts, setToasts] = useState<{ id: number; message: string }[]>([]);
  const [ready, setReady] = useState(false);
  const sourceRef = useRef<Source | null>(null);
  const toastId = useRef(0);
  const activePaymentId = state.payment?.paymentId;

  useEffect(() => {
    dispatch({ type: "ui.sourceChanged" });
    const source =
      sourceKind === "live"
        ? createLiveSource(engineUrl)
        : createReplaySource();
    sourceRef.current = source;
    let opened = false;
    let initialTimer: ReturnType<typeof setTimeout> | undefined;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const switchToReplay = () => {
      setNotice(offlineNotice);
      setSourceKindState("replay");
    };

    source.start({
      onEvent(event) {
        dispatch(event);
      },
      onStatus(status) {
        if (status.notice) setNotice(status.notice);
        if (status.connected) setReady(true);
        if (status.kind !== "live") return;
        if (status.connected) {
          opened = true;
          if (initialTimer) clearTimeout(initialTimer);
          if (reconnectTimer) clearTimeout(reconnectTimer);
          return;
        }
        if (opened) {
          if (reconnectTimer) clearTimeout(reconnectTimer);
          reconnectTimer = setTimeout(switchToReplay, 5000);
        }
      },
    });

    if (sourceKind === "live") {
      initialTimer = setTimeout(() => {
        if (!opened) switchToReplay();
      }, engineConnectTimeoutMs);
    }

    return () => {
      if (initialTimer) clearTimeout(initialTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      source.stop();
      if (sourceRef.current === source) sourceRef.current = null;
    };
  }, [sourceKind]);

  const setSpeed = useCallback((nextSpeed: 1 | 2) => {
    setSpeedState(nextSpeed);
  }, []);

  const setSourceKind = useCallback((kind: SourceKind) => {
    setNotice(undefined);
    setSourceKindState(kind);
  }, []);

  const runScenario = useCallback(
    (name: ScenarioName, invoiceText?: string) =>
      sourceRef.current?.runScenario(name, {
        speed,
        ...(invoiceText === undefined ? {} : { invoiceText }),
      }) ?? Promise.resolve(),
    [speed],
  );
  const supplierResponse = useCallback(
    (answer: "confirm" | "deny") => {
      return activePaymentId && sourceRef.current
        ? sourceRef.current.supplierResponse(activePaymentId, answer)
        : Promise.resolve();
    },
    [activePaymentId],
  );
  const attack = useCallback((name: AttackName) => {
    return activePaymentId && sourceRef.current
      ? sourceRef.current.attack(activePaymentId, name)
      : Promise.resolve();
  }, [activePaymentId]);
  const reset = useCallback(
    () => sourceRef.current?.reset() ?? Promise.resolve(),
    [],
  );
  const dismissAlert = useCallback(() => {
    dispatch({ type: "ui.closeAlert" });
  }, []);
  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);
  const pushToast = useCallback((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    setToasts((current) =>
      [...current, { id: ++toastId.current, message }].slice(-2),
    );
  }, []);
  const safeAction = useCallback(
    async (action: () => void | Promise<void>) => {
      try {
        await action();
      } catch (error) {
        pushToast(error);
      }
    },
    [pushToast],
  );

  return {
    state,
    sourceKind,
    notice,
    ready,
    speed,
    setSpeed,
    setSourceKind,
    toasts,
    dismissToast,
    actions: {
      runLegit: () => safeAction(() => runScenario("legit")),
      runDiverted: (invoiceText?: string) =>
        safeAction(() => runScenario("diverted", invoiceText)),
      runMuleWave: () => safeAction(() => runScenario("muleWave")),
      runGuardian: () =>
        safeAction(() =>
          sourceKind === "live"
            ? attack("stolen_verifier_key")
            : runScenario("guardian"),
        ),
      runOutage: () => safeAction(() => runScenario("outage")),
      runSimSwap: () => safeAction(() => runScenario("diverted_simswap")),
      runHoldExpiry: () => safeAction(() => runScenario("diverted_expiry")),
      runTimeLock: () => safeAction(() => runScenario("diverted_timelock")),
      runConfidential: () => safeAction(() => runScenario("confidential")),
      confirm: () => safeAction(() => supplierResponse("confirm")),
      deny: () => safeAction(() => supplierResponse("deny")),
      attack: () => safeAction(() => attack("release_revoked")),
      swapAttack: () => safeAction(() => attack("swap_beneficiary")),
      replayAttack: () => safeAction(() => attack("replay")),
      reset: () => safeAction(reset),
      closeAlert: () => safeAction(dismissAlert),
    },
    available: availableActions(state, sourceKind),
  };
}
