def end(state):
    return state


def route_event(state):
    state.data["event_type"] = state.data.get("event_type", "route_completed")
    return state
