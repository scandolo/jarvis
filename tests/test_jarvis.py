import jarvis.decider as D
from jarvis.cost_guard import CostGuard


def _answer(choice, question="next_step"):
    return {"answers": {question: {"type": "choice", "choice": choice, "confidence": .9}}}


def test_root_is_one_decision_with_real_direct_actions():
    choices = D.build_root_choices()
    assert "app__arc" in choices
    assert "app__conductor" in choices
    assert "app__chatgpt" in choices
    assert "system__brightness_up" in choices
    assert "system__brightness_down" in choices
    assert "system__volume_down" in choices
    assert "social__share_love" in choices
    assert "control__wait_more" in choices


def test_model_selected_app_executes(monkeypatch):
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer("app__arc"))
    result = D.step("Can you open Arc please?", {"front_app": "Finder", "elements": []})
    assert result["action"] == "execute"
    assert result["capability"]["executor"]["bundle_id"] == "company.thebrowser.Browser"


def test_low_confidence_app_open_asks_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(D, "decide", lambda state, questions: {
        "answers": {"next_step": {"choice": "app__safari", "confidence": 0.32}}
    })
    result = D.step("Jarvis poi aprir por favor é do meu browser", {"elements": []})
    assert result["action"] == "clarify"


def test_model_selected_adjustment_is_safe(monkeypatch):
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer("system__brightness_down"))
    result = D.step("lower the brightness", {"front_app": "Finder", "elements": []})
    assert result["action"] == "execute"
    assert result["capability"]["effects"] == ("system_adjustment",)


def test_model_can_wait_for_more_speech(monkeypatch):
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer("control__wait_more"))
    result = D.step("open the", {"front_app": "Finder", "elements": []})
    assert result["action"] == "wait_more_speech"


def test_gratitude_can_select_hearts(monkeypatch):
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer("social__share_love"))
    result = D.step("Thank you Jev", {"front_app": "Finder", "elements": []})
    assert result["capability"]["executor"]["type"] == "share_love"


def test_visible_note_is_offered_and_selected(monkeypatch):
    snap = {
        "front_app": "Notes",
        "front_bundle_id": "com.apple.Notes",
        "elements": [
            {"id": "note_0", "kind": "note_row", "role": "AXRow", "label": "BOOKMARKS LIBRI"}
        ],
        "history": [{"transcript": "open Notes", "capability": "app__notes", "outcome": "opened Notes"}],
    }
    seen = []

    def choose(state, questions):
        seen.append((state, questions))
        return _answer("visible__note_0")

    monkeypatch.setattr(D, "decide", choose)
    result = D.step("open the bookmarks note", snap)
    assert result["action"] == "execute"
    assert result["capability"]["executor"]["type"] == "native_select"
    assert "visible__note_0" in seen[0][1]["next_step"]["criteria"]
    assert seen[0][0]["recent_interactions"] == snap["history"]


def test_arc_tab_is_grounded_in_visible_native_target(monkeypatch):
    snap = {
        "front_app": "Arc",
        "front_bundle_id": "company.thebrowser.Browser",
        "elements": [{"id": "arc_tab_0", "kind": "arc_tab", "label": "Dashboard"}],
        "screen_context": [{"role": "AXHeading", "label": "Deepgram"}],
    }
    seen = []

    def choose(state, questions):
        seen.append(state)
        return _answer("visible__arc_tab_0")

    monkeypatch.setattr(D, "decide", choose)
    result = D.step("switch to the Dashboard tab", snap)
    assert result["action"] == "execute"
    assert result["capability"]["executor"]["kind"] == "arc_tab"
    assert seen[0]["screen_context"] == snap["screen_context"]


def test_google_result_is_offered_only_from_search_page(monkeypatch):
    snap = {
        "front_app": "Arc", "front_bundle_id": "company.thebrowser.Browser",
        "page_url": "google.com/search",
        "elements": [{
            "id": "google_result_0", "kind": "google_result", "label": "Example article",
            "destination": "https://example.com/article",
        }],
    }
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer("visible__google_result_0"))
    result = D.step("open the example article", snap)
    assert result["action"] == "execute"
    assert result["capability"]["executor"]["destination"] == "https://example.com/article"


def test_visible_calendar_event_is_selectable(monkeypatch):
    snap = {"front_app": "Calendar", "front_bundle_id": "com.apple.iCal", "elements": [
        {"id": "calendar_event_0", "kind": "calendar_event", "label": "Compleanno Anna"},
    ]}
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer("visible__calendar_event_0"))
    result = D.step("clicca Compleanno Anna", snap)
    assert result["action"] == "execute"
    assert result["capability"]["executor"]["kind"] == "calendar_event"


def test_notion_page_offers_grounded_slash_workflows(monkeypatch):
    snap = {"front_app": "Notion", "front_bundle_id": "notion.id",
            "window_title": "Project plan", "elements": []}
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer("notion__insert_database"))
    result = D.step("aggiungi un database in questa pagina", snap)
    assert result["action"] == "await_confirm"
    assert result["capability"]["executor"] == {
        "type": "notion_insert", "block": "database", "window_title": "Project plan"
    }
    assert "notion__insert_database" not in D.build_root_choices({"front_app": "Notes"})


def test_arc_search_query_is_selected_by_jev_not_parsed_locally(monkeypatch):
    choices = iter(["branch__arc_search", "arc_search__1"])
    seen = []

    def choose(state, questions):
        seen.append(questions["next_step"]["criteria"])
        return _answer(next(choices))

    monkeypatch.setattr(D, "decide", choose)
    result = D.step("Search pasta in Rome", {"front_app": "Arc", "elements": []})
    assert result["action"] == "execute"
    assert result["capability"]["executor"] == {"type": "arc_search", "query": "pasta in Rome"}
    assert "branch__arc_search" in seen[0]


def test_social_reaction_choices_are_offered():
    choices = D.build_root_choices()
    assert "social__playful_anger" in choices
    assert "social__share_sadness" in choices


def test_unavailable_request_is_not_mislabeled_security(monkeypatch):
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer("control__unsupported"))
    result = D.step("make a calendar event", {"front_app": "Calendar", "elements": []})
    assert result["action"] == "unsupported"


def test_application_branch_is_deterministic(monkeypatch):
    calls = []

    def choose(state, questions):
        calls.append((state, questions))
        if len(calls) == 1:
            return _answer("branch__applications")
        assert any(
            description.startswith("Open or focus")
            for description in questions["next_step"]["criteria"].values()
        )
        return _answer("app__arc")

    monkeypatch.setattr(D, "decide", choose)
    result = D.step("Open Arc", {"front_app": "Finder", "elements": []})
    assert result["action"] == "execute"
    assert len(calls) == 2


def test_window_layout_selects_two_fresh_windows(monkeypatch):
    snap = {"front_app": "Conductor", "elements": [], "windows": [
        {"id": "window_10_0", "app": "Conductor", "bundle_id": "com.conductor.app", "title": "Jarvis"},
        {"id": "window_20_0", "app": "Notes", "bundle_id": "com.apple.Notes", "title": "Notes"},
    ]}
    choices = iter(["branch__window_layout", "window_10_0", "window_20_0"])
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer(next(choices)))
    result = D.step("metti Conductor a sinistra e Note a destra", snap)
    assert result["action"] == "execute"
    assert result["capability"]["executor"]["type"] == "tile_windows"
    assert result["capability"]["executor"]["left_title"] == "Jarvis"


def test_window_layout_needs_two_windows(monkeypatch):
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer("branch__window_layout"))
    result = D.step("metti le finestre affiancate", {"windows": [], "elements": []})
    assert result["action"] == "clarify"


def test_current_window_layout_actions_are_grounded(monkeypatch):
    snap = {"front_app": "Notes", "front_bundle_id": "com.apple.Notes",
            "window_title": "Notes", "elements": [], "windows": [
                {"id": "window_20_0", "app": "Notes",
                 "bundle_id": "com.apple.Notes", "title": "Notes"},
            ]}
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer("window__right"))
    result = D.step("metti questa finestra a destra", snap)
    assert result["action"] == "execute"
    assert result["capability"]["executor"]["placement"] == "right"


def test_calendar_event_uses_model_chosen_title_date_time_and_confirmation(monkeypatch):
    from datetime import datetime, timedelta
    tomorrow = (datetime.now().astimezone() + timedelta(days=1)).date()
    transcript = "aggiungi evento pranzo con Luca domani alle 13"
    stages = []

    def choose(state, questions):
        stages.append(state["stage"])
        if state["stage"] == "root":
            return _answer("branch__calendar_event")
        offered = questions["next_step"]["criteria"]
        if state["stage"] == "calendar_title":
            return _answer(next(key for key, value in offered.items()
                                if "'pranzo con Luca'" in value))
        if state["stage"] == "calendar_date":
            return _answer(next(key for key, value in offered.items()
                                if tomorrow.isoformat() in value))
        if state["stage"] == "calendar_time":
            return _answer("time__13_00")
        return _answer("duration__60")

    monkeypatch.setattr(D, "decide", choose)
    result = D.step(transcript, {"front_app": "Calendar", "elements": []})
    assert result["action"] == "await_confirm"
    assert result["capability"]["executor"]["title"] == "pranzo con Luca"
    assert result["capability"]["executor"]["duration_minutes"] == 60
    assert stages == ["root", "calendar_title", "calendar_date", "calendar_time", "calendar_duration"]


def test_text_candidates_are_bounded():
    capabilities = D._text_capabilities(" ".join(f"w{i}" for i in range(100)))
    assert len(capabilities) <= 80


def test_cost_cap_blocks(monkeypatch):
    monkeypatch.setattr(D, "decide", lambda state, questions: _answer("app__arc"))
    D.guard.spent = 4.999
    monkeypatch.setattr(CostGuard, "estimate_tokens", staticmethod(lambda state, questions: 10_000_000))
    result = D.step("open notes", {"front_app": "Finder", "elements": []})
    assert result["action"] == "blocked_cost"
    D.guard.spent = 0


def test_no_secrets_in_repo():
    import pathlib
    for file in pathlib.Path("jarvis").glob("*.py"):
        text = file.read_text()
        assert "sk-" not in text and "TYPESAFE_API_KEY=" not in text.replace("os.getenv", ""), file
