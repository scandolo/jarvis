"""Jev-routed, capability-constrained decision tree.

Jev performs the language understanding. Python supplies real options, follows
the selected branch, and refuses anything outside the capability registry.
"""
from datetime import datetime, timedelta

from .capabilities import (
    CONTROL_CRITERIA,
    Capability,
    application_capabilities,
    contextual_capabilities,
    criteria,
    direct_capabilities,
    setting_capabilities,
    visible_capabilities,
)
from .cost_guard import CostGuard
from .devlog import trace
from .jev_client import decide
from .security import inspect_capability


guard = CostGuard()


def _choice(response: dict, question: str = "next_step"):
    answer = (response.get("answers") or {}).get(question)
    if isinstance(answer, dict):
        return answer.get("choice")
    if isinstance(answer, str):
        return answer
    return None


def _state(transcript: str, snap: dict, stage: str) -> dict:
    state = {
        "input_kind": "push-to-talk microphone transcript",
        "transcript": transcript,
        "stage": stage,
        "local_now": snap.get("calendar_now") or datetime.now().astimezone().isoformat(),
        "front_app": snap.get("front_app"),
        "front_bundle_id": snap.get("front_bundle_id"),
        "window_title": snap.get("window_title"),
        "page_url": snap.get("page_url"),
        "visible_elements": snap.get("elements", [])[:100],
        "screen_context": snap.get("screen_context", [])[:70],
        "open_windows": snap.get("windows", [])[:30],
        "recent_interactions": snap.get("history", [])[-4:],
        "instruction": (
            "Infer the user's intended Mac action semantically from their speech. "
            "Choose exactly one offered transition. Do not invent an action. "
            "Use recent interactions to resolve corrections such as 'I meant decrease'. "
            "Opening an app is not a substitute for acting inside it. "
            "Use screen context to understand references to the current page, but only executable "
            "visible targets are offered as choices. If the requested in-app action is unavailable, "
            "select unsupported or clarify. "
            "A thank-you addressed to Jarvis is a social message: select share_love. "
            "A playful insult addressed to Jarvis can choose playful_anger; a lighthearted sad "
            "remark can choose share_sadness. Do not use emoji reactions for serious distress. "
            "Use wait_more only for a genuinely unfinished thought."
            " If speech ambiguously mentions a browser without naming one, ask which browser."
        ),
    }
    if stage == "arc_search":
        state["search_instruction"] = (
            "Choose a substantive search subject from the user's own words. "
            "A vague placeholder such as 'something' is not a usable query: "
            "select wait_more or clarify until the user supplies a topic."
        )
    return state


def _window_layout(transcript: str, snap: dict):
    windows = snap.get("windows", [])[:30]
    if len(windows) < 2:
        return {"action": "clarify", "transcript": transcript,
                "message": "I need two available app windows to arrange side by side."}
    choices = {
        window["id"]: f"{window.get('app', 'App')} window {window.get('title') or '(untitled)'}"
        for window in windows if window.get("id") and window.get("bundle_id")
    }
    controls = {key: CONTROL_CRITERIA[key] for key in ("control__clarify", "control__unsupported")}
    left_choice, response, cost = _ask(
        transcript, snap, "window_layout_left", {
            **{key: "Put this window on the LEFT: " + value for key, value in choices.items()},
            **controls,
        }
    )
    if left_choice not in choices:
        return _control_result(left_choice, transcript, response, cost) or {
            "action": "clarify", "transcript": transcript,
            "message": "Which app should be on the left?",
        }
    right_choices = {key: value for key, value in choices.items() if key != left_choice}
    right_choice, response, cost = _ask(
        transcript, snap, "window_layout_right", {
            **{key: "Put this window on the RIGHT: " + value for key, value in right_choices.items()},
            **controls,
        }
    )
    if right_choice not in right_choices:
        return _control_result(right_choice, transcript, response, cost) or {
            "action": "clarify", "transcript": transcript,
            "message": "Which app should be on the right?",
        }
    left = next(window for window in windows if window["id"] == left_choice)
    right = next(window for window in windows if window["id"] == right_choice)
    capability = Capability(
        id=f"layout__{left_choice}__{right_choice}",
        label=f"Arrange {left['app']} and {right['app']} side by side",
        description="Resize and place the two existing windows on the current desktop.",
        effects=("window_layout",),
        executor={
            "type": "tile_windows", "left_id": left_choice, "right_id": right_choice,
            "left_bundle_id": left["bundle_id"], "right_bundle_id": right["bundle_id"],
            "left_title": left.get("title", ""), "right_title": right.get("title", ""),
        },
    )
    return _resolve_capability(capability, transcript, snap, response, cost)


def _calendar_event(transcript: str, snap: dict):
    now = datetime.now().astimezone()
    controls = {
        "control__clarify": "A required event detail was not actually spoken; ask for it.",
        "control__unsupported": "The requested event is outside the offered safe date/time range.",
    }
    titles = {
        f"title__{index}": candidate
        for index, candidate in enumerate(_text_candidates(transcript))
    }
    title_choice, response, cost = _ask(transcript, snap, "calendar_title", {
        **{key: f"Use exactly {value!r} as the event title; omit command and date words."
           for key, value in titles.items()},
        **controls,
    })
    if title_choice not in titles:
        return _control_result(title_choice, transcript, response, cost) or {
            "action": "clarify", "transcript": transcript,
            "message": "What should I call the event?",
        }
    dates = {}
    for offset in range(0, 91):
        day = now.date() + timedelta(days=offset)
        dates[f"date__{offset}"] = day
    date_choice, response, cost = _ask(transcript, {
        **snap, "calendar_now": now.isoformat(),
    }, "calendar_date", {
        **{key: f"Event date {day.isoformat()} ({day.strftime('%A')}); select only if the user specified this date."
           for key, day in dates.items()},
        **controls,
    })
    if date_choice not in dates:
        return _control_result(date_choice, transcript, response, cost) or {
            "action": "clarify", "transcript": transcript,
            "message": "Which date should I put in Calendar?",
        }
    times = {f"time__{hour:02d}_{minute:02d}": (hour, minute)
             for hour in range(24) for minute in (0, 30)}
    time_choice, response, cost = _ask(transcript, snap, "calendar_time", {
        **{key: f"Start at {hour:02d}:{minute:02d} local time; select only if this time was spoken."
           for key, (hour, minute) in times.items()},
        **controls,
    })
    if time_choice not in times:
        return _control_result(time_choice, transcript, response, cost) or {
            "action": "clarify", "transcript": transcript,
            "message": "At what time should the event start?",
        }
    durations = {"duration__30": 30, "duration__60": 60,
                 "duration__90": 90, "duration__120": 120}
    duration_choice, response, cost = _ask(transcript, snap, "calendar_duration", {
        **{key: (f"Event lasts {minutes} minutes. " +
                  ("Use as default if no duration was spoken." if minutes == 60
                   else "Select only if this duration was spoken."))
           for key, minutes in durations.items()},
        **controls,
    })
    if duration_choice not in durations:
        return _control_result(duration_choice, transcript, response, cost) or {
            "action": "clarify", "transcript": transcript,
            "message": "How long should the event last?",
        }
    hour, minute = times[time_choice]
    start = datetime.combine(dates[date_choice], datetime.min.time()).replace(
        hour=hour, minute=minute
    ).astimezone()
    if start <= now:
        return {"action": "clarify", "transcript": transcript,
                "message": "That start time has already passed. What time should I use?"}
    title = titles[title_choice]
    minutes = durations[duration_choice]
    capability = Capability(
        id="calendar__create_event",
        label=f"Add “{title}” on {start.strftime('%d/%m/%Y %H:%M')} for {minutes} min",
        description=f"Create {title!r} at {start.isoformat()} for {minutes} minutes.",
        effects=("create_content",),
        executor={"type": "create_calendar_event", "title": title,
                  "start": start.isoformat(), "duration_minutes": minutes},
        requires_confirmation=True,
    )
    return _resolve_capability(capability, transcript, snap, response, cost)


def _ask(transcript: str, snap: dict, stage: str, choices: dict):
    questions = {
        "next_step": {
            "type": "choice",
            "instructions": (
                "Select the single best next transition for what the user meant. "
                "The transcript comes from speech recognition and may contain spacing, "
                "punctuation, or phonetic mistakes. Distinguish launching an app from "
                "opening a document or doing something within that app."
            ),
            "criteria": choices,
        }
    }
    state = _state(transcript, snap, stage)
    cost = guard.record(CostGuard.estimate_tokens(state, questions))
    if cost["blocked"]:
        trace("decision.cost_blocked", stage=stage, transcript=transcript, cost=cost)
        return None, None, cost
    response = decide(state, questions)
    choice = _choice(response)
    trace(
        "decision.stage",
        stage=stage,
        transcript=transcript,
        offered_choices=list(choices),
        selected_choice=choice,
        response=response,
        cost=cost,
    )
    return choice, response, cost


def _text_candidates(transcript: str):
    words = transcript.split()
    if not words:
        return []
    words = words[-20:]
    candidates = []

    def add(value):
        value = value.strip()
        if value and value not in candidates:
            candidates.append(value)

    add(" ".join(words))
    for start in range(len(words)):
        add(" ".join(words[start:]))
    for width in range(min(8, len(words)), 0, -1):
        for start in range(0, len(words) - width + 1):
            add(" ".join(words[start:start + width]))
            if len(candidates) >= 80:
                return candidates
    return candidates


def _text_capabilities(transcript: str):
    capabilities = {}
    for index, text in enumerate(_text_candidates(transcript)):
        capability = Capability(
            id=f"text__{index}",
            label=f"Type “{text}”",
            description=f"Type exactly this transcript span into the focused field: {text!r}",
            effects=("type_text",),
            executor={"type": "type_text", "text": text},
        )
        capabilities[capability.id] = capability
    return capabilities


def _arc_search_capabilities(transcript: str):
    capabilities = {}
    for index, query in enumerate(_text_candidates(transcript)):
        capability = Capability(
            id=f"arc_search__{index}",
            label=f"Search Arc for “{query}”",
            description=(
                f"Search Google in the Arc browser for exactly {query!r}. "
                "Choose the user's subject, without speech filler or command words."
            ),
            effects=("web_navigation",),
            executor={"type": "arc_search", "query": query},
        )
        capabilities[capability.id] = capability
    return capabilities


def _control_result(choice, transcript, response, cost):
    common = {"transcript": transcript, "decision": response, "cost": cost}
    if choice == "control__wait_more":
        return {"action": "wait_more_speech", **common}
    if choice == "control__clarify":
        return {"action": "clarify", **common}
    if choice == "control__no_action":
        return {"action": "no_action", **common}
    if choice == "control__unsupported":
        return {
            "action": "unsupported",
            "message": "I understand, but I can't safely do that yet.",
            **common,
        }
    return None


def _resolve_capability(capability, transcript, snap, response, cost):
    answer = ((response or {}).get("answers") or {}).get("next_step") or {}
    confidence = answer.get("confidence") if isinstance(answer, dict) else None
    if (capability.executor.get("type") == "open_bundle" and
        isinstance(confidence, (int, float)) and confidence < 0.4):
        return {
            "action": "clarify", "message": "Which application should I open?",
            "transcript": transcript, "decision": response, "cost": cost,
        }
    block = inspect_capability(capability.to_dict(), snap)
    if block:
        return {
            "action": "blocked_security",
            "security": block.__dict__,
            "transcript": transcript,
            "decision": response,
            "cost": cost,
        }
    return {
        "action": "await_confirm" if capability.requires_confirmation else "execute",
        "capability": capability.to_dict(),
        "transcript": transcript,
        "decision": response,
        "cost": cost,
    }


def _branch(transcript, snap, stage, capabilities):
    branch_choices = criteria(capabilities.values())
    branch_choices.update({
        key: value for key, value in CONTROL_CRITERIA.items()
        if key in {"control__wait_more", "control__clarify", "control__unsupported"}
    })
    choice, response, cost = _ask(transcript, snap, stage, branch_choices)
    if choice is None and cost and cost.get("blocked"):
        return {"action": "blocked_cost", "cost": cost, "transcript": transcript}
    control = _control_result(choice, transcript, response, cost)
    if control:
        return control
    capability = capabilities.get(choice)
    if capability is None:
        trace("decision.invalid_choice", stage=stage, selected_choice=choice)
        return {
            "action": "clarify",
            "transcript": transcript,
            "decision": response,
            "cost": cost,
        }
    return _resolve_capability(capability, transcript, snap, response, cost)


def build_root_choices(snap=None):
    choices = criteria(direct_capabilities().values())
    if snap:
        choices.update(criteria(visible_capabilities(snap).values()))
        choices.update(criteria(contextual_capabilities(snap).values()))
    choices.update(CONTROL_CRITERIA)
    return choices


def step(transcript: str, snap: dict):
    capabilities = {
        **direct_capabilities(),
        **visible_capabilities(snap),
        **contextual_capabilities(snap),
    }
    choice, response, cost = _ask(transcript, snap, "root", {
        **criteria(capabilities.values()),
        **CONTROL_CRITERIA,
    })
    if choice is None and cost and cost.get("blocked"):
        return {"action": "blocked_cost", "cost": cost, "transcript": transcript}

    control = _control_result(choice, transcript, response, cost)
    if control:
        return control
    capability = capabilities.get(choice)
    if capability is not None:
        return _resolve_capability(capability, transcript, snap, response, cost)

    if choice == "branch__applications":
        return _branch(transcript, snap, "applications", application_capabilities())
    if choice == "branch__settings":
        return _branch(transcript, snap, "settings", setting_capabilities())
    if choice == "branch__window_layout":
        return _window_layout(transcript, snap)
    if choice == "branch__calendar_event":
        return _calendar_event(transcript, snap)
    if choice == "branch__text":
        return _branch(transcript, snap, "text", _text_capabilities(transcript))
    if choice == "branch__arc_search":
        result = _branch(transcript, snap, "arc_search", _arc_search_capabilities(transcript))
        if result.get("action") == "clarify":
            result["message"] = "What should I search for in Arc?"
        return result
    if choice == "branch__visible_ui":
        visible = visible_capabilities(snap)
        if visible:
            return _branch(transcript, snap, "visible_ui", visible)
        trace("decision.visible_ui_unavailable", elements=snap.get("elements", []))
        return {
            "action": "clarify",
            "transcript": transcript,
            "decision": response,
            "cost": cost,
            "message": "I can see the current app, but safe control-level interaction is not available yet.",
        }

    trace("decision.invalid_choice", stage="root", selected_choice=choice)
    return {
        "action": "clarify",
        "transcript": transcript,
        "decision": response,
        "cost": cost,
    }


def resolve_confirmation(transcript: str, pending_result: dict, snap: dict):
    capability = pending_result.get("capability") or {}
    state = {
        "input_kind": "push-to-talk microphone transcript",
        "transcript": transcript,
        "pending_action": {
            "id": capability.get("id"),
            "label": capability.get("label"),
            "effects": capability.get("effects"),
        },
        "instruction": "Decide whether the user confirms, cancels, or has not answered the confirmation.",
    }
    questions = {
        "confirmation": {
            "type": "choice",
            "instructions": "Interpret the user's reply to the pending confirmation.",
            "criteria": {
                "confirm": "The user clearly approves the pending action.",
                "cancel": "The user refuses, cancels, or changes their mind.",
                "wait": "The reply does not clearly confirm or cancel.",
            },
        }
    }
    cost = guard.record(CostGuard.estimate_tokens(state, questions))
    if cost["blocked"]:
        return "wait", None, cost
    response = decide(state, questions)
    choice = _choice(response, "confirmation")
    trace(
        "decision.confirmation",
        transcript=transcript,
        pending_capability=capability,
        selected_choice=choice,
        response=response,
        cost=cost,
    )
    return choice if choice in {"confirm", "cancel", "wait"} else "wait", response, cost
