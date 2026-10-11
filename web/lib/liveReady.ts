import { initialState, type ViewState } from "./store";

export function readyAfterTerminalBacklog(state: ViewState): ViewState {
  const terminal =
    state.payment?.status === "credited" ||
    state.payment?.status === "stopped" ||
    state.refunded;
  if (!terminal) return state;

  return {
    ...initialState,
    mode: state.mode,
    rails: state.rails,
    killSwitch: state.killSwitch,
    lastSeq: state.lastSeq,
  };
}
