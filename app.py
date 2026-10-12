"""AtliQ Contract Risk Analyzer - Streamlit UI (PRD section 11).

    streamlit run app.py

Tab 1 reviews one contract in five steps and records a human decision.
Tab 2 answers grounded questions about AtliQ's contracts.
The app never signs, sends or approves anything (GR-01).
"""

from __future__ import annotations

import streamlit as st

import config

st.set_page_config(page_title="AtliQ Contract Risk Analyzer", page_icon="📑", layout="wide")

import ingest  # noqa: E402
import qa  # noqa: E402
import register  # noqa: E402
import review  # noqa: E402
import rules  # noqa: E402
from llm import MissingKeyError  # noqa: E402

RISK_BADGE = {
    "High": ":red-background[**High**]",
    "Medium": ":orange-background[**Medium**]",
    "Low": ":blue-background[Low]",
    "Needs human reading": ":gray-background[Needs human reading]",
}
DECISIONS = {"Accept": rules.ACCEPT, "Redline": rules.REDLINE, "Send to lawyer": rules.SEND_TO_LAWYER}
AI_LABEL = "AI suggestion. You decide."

state = st.session_state
for key, default in {
    "stage": None, "name": None, "text": None, "basics": None, "audit": None,
    "result": None, "decision": None, "pending_decision": None, "chat": [],
}.items():
    state.setdefault(key, default)


def reset_review() -> None:
    for key in ("stage", "name", "text", "basics", "audit", "result", "decision", "pending_decision"):
        state[key] = None


@st.cache_data(show_spinner=False)
def counts() -> dict[str, int]:
    return ingest.collection_counts()


# =============================================================================
# Sidebar
# =============================================================================
with st.sidebar:
    st.header("📑 AtliQ Contract Risk Analyzer")
    st.caption(f"Review date: {config.TODAY:%d %b %Y}. AI suggestions only; a person decides. Not legal advice.")

    contracts = review.list_contracts()
    labels = {f"{p.parent.name}/{p.name}": p for p in contracts}
    choice = st.selectbox("Contract to review", list(labels), index=None, placeholder="Pick an incoming draft")
    upload = st.file_uploader("…or upload one", type=["md", "txt", "pdf", "docx"])
    run = st.button("▶ Run review", type="primary", use_container_width=True)

    st.divider()
    st.subheader("Commitments register")
    entries = rules.load_register()
    confirmed = [e for e in entries if e.get("confirmed_by_human")]
    unconfirmed = [e for e in entries if not e.get("confirmed_by_human")]
    st.caption(f"{len(confirmed)} confirmed, {len(unconfirmed)} awaiting confirmation. Only confirmed entries are used in reviews.")
    if st.button("🔄 Rebuild register", use_container_width=True,
                 help="Reads every signed contract and proposes new entries. Proposals stay unused until you confirm them."):
        with st.status("Rebuilding register…", expanded=True) as status:
            try:
                proposals = register.rebuild(progress=status.write)
                ingest.ingest_commitments()
                status.update(label=f"{len(proposals)} new proposal(s) added", state="complete")
            except MissingKeyError as error:
                status.update(label=str(error), state="error")
        counts.clear()
    if unconfirmed:
        with st.expander(f"Review {len(unconfirmed)} proposed entr{'y' if len(unconfirmed) == 1 else 'ies'}"):
            ticked = []
            for entry in unconfirmed:
                st.markdown(f"**{entry['id']}** · {entry['type']} · `{entry['source_file']}` clause {entry['clause']}")
                st.caption(entry["summary"])
                if st.checkbox("Confirm", key=f"confirm_{entry['id']}"):
                    ticked.append(entry["id"])
            if st.button("Save confirmations", disabled=not ticked):
                register.confirm(ticked)
                ingest.ingest_commitments()
                counts.clear()
                st.rerun()

    st.divider()
    kb = counts()
    if kb:
        st.caption("Knowledge base: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in kb.items()))

if not kb or not any(kb.values()):
    # First start on a fresh machine or on Streamlit Community Cloud: build it.
    with st.spinner("Building the knowledge base (first start only, about a minute)…"):
        ingest.main()
    counts.clear()
    st.rerun()

review_tab, qa_tab = st.tabs(["Review a contract", "Ask about our contracts"])


# =============================================================================
# Tab 1 - Review
# =============================================================================
def start_review() -> None:
    if upload is not None:
        try:
            text = review.extract_text(upload.name, upload.getvalue())
        except review.UnreadableFile as error:
            st.error(str(error))
            return
        name = f"upload: {upload.name}"
    elif choice:
        text = labels[choice].read_text(encoding="utf-8")
        name = labels[choice].name
    else:
        st.warning("Pick a contract or upload one first.")
        return

    # FR-03, GR-08: block personal / patient data before anything else happens.
    hits = review.personal_data_check(text)
    if hits:
        reset_review()
        st.error(
            "This file appears to contain personal or patient data ("
            + ", ".join(hits)
            + "). It was not processed or stored. Remove the data and try again."
        )
        return

    reset_review()
    state.name, state.text = name, text
    state.audit = review.Audit(name)
    with st.status("Step 2: identifying the basics…", expanded=True) as status:
        try:
            state.basics = review.run_basics(name, text, state.audit, progress=status.write)
        except MissingKeyError as error:
            status.update(label=str(error), state="error")
            return
        except Exception as error:
            status.update(label=f"The AI step failed: {error}", state="error")
            return
        status.update(label="Step 2 done: check the basics below", state="complete")
    state.stage = "basics"


def basics_card(editable: bool) -> None:
    basics = state.basics
    st.subheader("1 · Basics")
    st.caption(AI_LABEL + " Every field shows the contract text it came from.")
    corrections = {}
    columns = st.columns(3)
    for index, (key, label) in enumerate(review.BASIC_FIELDS):
        item = basics.get(key) if isinstance(basics.get(key), dict) else {"value": basics.get(key)}
        value = item.get("value")
        with columns[index % 3]:
            if editable:
                if key == "healthcare":
                    corrections[key] = st.checkbox(label, value=bool(value), key=f"edit_{state.name}_{key}")
                elif key in {"contract_value", "term_months"}:
                    corrections[key] = st.number_input(label, value=float(value) if isinstance(value, (int, float)) else None,
                                                       placeholder=review.NOT_FOUND, key=f"edit_{state.name}_{key}")
                else:
                    corrections[key] = st.text_input(label, value=str(value) if value not in (None, "") else "",
                                                     placeholder=review.NOT_FOUND, key=f"edit_{state.name}_{key}") or None
            else:
                shown = value if value not in (None, "") else review.NOT_FOUND
                if key == "contract_value" and isinstance(value, (int, float)):
                    shown = f"{item.get('currency') or ''} {value:,.0f}".strip()
                st.markdown(f"**{label}**  \n{shown}" + ("  ✏️ *corrected*" if item.get("corrected_by_user") else ""))
            if item.get("quote"):
                st.caption(f"“{item['quote']}”")
            elif not item.get("corrected_by_user"):
                st.caption(review.NOT_FOUND if value in (None, "") else "No supporting quote found")
    linked = basics.get("linked_documents_needed") or []
    if linked:
        st.markdown("**Linked documents needed:** " + ", ".join(map(str, linked)))
    if editable and st.button("✅ Confirm basics and continue the review", type="primary"):
        review.apply_corrections(basics, corrections, state.audit)
        with st.status("Running the review…", expanded=True) as status:
            try:
                state.result = review.run_rest(state.name, state.text, basics, state.audit, progress=status.write)
            except Exception as error:
                status.update(label=f"The review failed: {error}", state="error")
                return
            status.update(label="Review complete", state="complete")
        state.stage = "done"
        st.rerun()


def show_rule_flags(result) -> None:
    status = result.rule_status
    entity = status.get("entity_rule")
    if entity == "ok":
        st.success("Entity rule: the right AtliQ entity is named.", icon="✅")
    baa = status.get("baa_rule")
    if baa == "baa_missing":
        st.error(f"Healthcare project: {rules.BAA_MESSAGE} Parties checked: {status.get('baa_parties')}.", icon="🩺")
    elif baa == "baa_ok":
        st.success(f"Healthcare project: signed BAAs found for {status.get('baa_parties')}.", icon="🩺")


def related_section(result) -> None:
    st.subheader("2 · Related contracts and history")
    related = result.related
    if not related.get("related"):
        st.caption("No related documents found.")
    for item in related.get("related", []):
        with st.expander(f"`{item['file']}` · {', '.join(item['reasons'])}"):
            if item.get("section"):
                st.caption(item["section"])
            st.text(item["excerpt"])
    if related.get("tracker_rows"):
        with st.expander(f"Tracker rows for this counterparty ({len(related['tracker_rows'])})"):
            st.dataframe(
                [{k: r[k] for k in ("contract_id", "doc_type", "status", "signed_date", "value_usd", "notes")} for r in related["tracker_rows"]],
                hide_index=True, use_container_width=True,
            )
    if related.get("missing"):
        st.warning("**Expected but not found:** the tracker lists these documents, but they are not in the data folder.")
        st.dataframe(related["missing"], hide_index=True, use_container_width=True)


def findings_section(result) -> None:
    st.subheader("3 · Clause-by-clause findings")
    st.caption(AI_LABEL + " Serious findings first. 'Rule check' findings come from fixed code rules.")
    for part in result.unreviewed:
        st.warning(f"Needs human reading: the AI could not review {part}. Read this part yourself.", icon="👁")
    if not result.findings:
        st.info("No issues found in the checks run: " + "; ".join(result.checks_run) + ".")
    for f in result.findings:
        with st.container(border=True):
            source = "Rule check" if f.source == "rule" else "AI review"
            st.markdown(f"{RISK_BADGE.get(f.risk, f.risk)} **{f.title}** · clause {f.clause or '-'} · *{f.principle or ''}* · {source}")
            if f.quote:
                st.markdown(f"> {f.quote}")
            st.write(f.reason)
            if f.suggested_wording:
                st.caption(f"Suggested wording: {f.suggested_wording}")
            if f.past_reference:
                st.caption(f"Before: {f.past_reference}")
    if result.dropped:
        st.caption(f"{len(result.dropped)} AI finding(s) were dropped because their quote is not in the contract.")


def conflicts_section(result) -> None:
    st.subheader("4 · Past commitments")
    summary = result.commitment_summary
    if not result.conflicts:
        st.info(f"No conflict found in {summary.get('register_checked', 0)} confirmed register entries.")
        if summary.get("unconfirmed"):
            st.caption("Not checked (unconfirmed): " + ", ".join(summary["unconfirmed"]))
    for c in result.conflicts:
        with st.container(border=True):
            st.markdown(f"{RISK_BADGE[c.risk]} **{c.title}** · ends {c.end_date or 'never'}")
            st.write(c.reason)
            left, right = st.columns(2)
            with left:
                st.markdown("**This contract**")
                st.markdown(f"> {c.new_clause or '(see contract text)'}")
            with right:
                st.markdown(f"**Signed: `{c.source_file}` clause {c.clause}**")
                st.markdown(f"> {c.old_clause}")
            if c.waiver_note:
                (st.warning if c.risk == "Medium" else st.error)(c.waiver_note, icon="📄")
    for note in summary.get("notes", []):
        st.caption(note)


def suggestion_section(result) -> None:
    st.subheader("5 · Suggested next step")
    with st.container(border=True):
        st.caption(AI_LABEL)
        st.markdown(f"### {result.suggestion}")
        for reason in result.reasons:
            st.markdown(f"- {reason}")
        st.write(result.explanation.get("explanation", ""))
        if result.suggestion == rules.ACCEPT:
            st.caption("Checks run: " + "; ".join(result.checks_run) + ".")

    edits = review.redlines(result.findings)
    if result.suggestion == rules.REDLINE and edits:
        st.markdown("**Clauses to change** (edit these before sending; nothing is sent by this app)")
        st.dataframe(edits, hide_index=True, use_container_width=True)

    pack = review.lawyer_pack(result)
    st.download_button(
        "⬇ Download lawyer pack (markdown)",
        pack,
        file_name=f"lawyer_pack_{result.contract.replace('upload: ', '').rsplit('.', 1)[0]}.md",
        mime="text/markdown",
        type="primary" if result.suggestion == rules.SEND_TO_LAWYER else "secondary",
    )


def decision_section(result) -> None:
    st.subheader("Your decision")
    st.caption("Recording a decision does nothing to the contract. Nothing is signed, approved or sent.")
    if state.decision:
        st.success(f"Recorded: **{state.decision}**. Saved to `logs/decisions.csv`.")
        return
    columns = st.columns(3)
    for column, label in zip(columns, DECISIONS):
        if column.button(label, use_container_width=True, key=f"decide_{label}"):
            state.pending_decision = label
    pending = state.pending_decision
    if not pending:
        return
    if DECISIONS[pending] == result.suggestion:
        review.record_decision(result.contract, result.suggestion, pending, "", state.audit)
        state.decision = pending
        st.rerun()
    reason = st.text_input(f"You chose **{pending}**, but the AI suggested **{result.suggestion}**. Why? (required)")
    if st.button("Save decision", disabled=not reason.strip()):
        review.record_decision(result.contract, result.suggestion, pending, reason.strip(), state.audit)
        state.decision = pending
        st.rerun()


with review_tab:
    if run:
        start_review()

    if state.stage is None:
        st.title("Review a contract")
        st.write("Pick an incoming draft or upload a contract in the sidebar, then **Run review**. "
                 "The assistant identifies the basics, finds related contracts, reviews each clause against "
                 "AtliQ's principles, checks promises already made, and suggests a next step. You decide.")
    else:
        st.title(state.name)
        with st.expander("Contract text"):
            st.text(state.text)
        basics_card(editable=state.stage == "basics")
        if state.stage == "done" and state.result:
            result = state.result
            show_rule_flags(result)
            st.divider()
            related_section(result)
            st.divider()
            findings_section(result)
            st.divider()
            conflicts_section(result)
            st.divider()
            suggestion_section(result)
            st.divider()
            decision_section(result)
        if state.audit:
            with st.expander("Audit log"):
                st.code("\n".join(state.audit.lines) or "(empty)", language="text")


# =============================================================================
# Tab 2 - Q&A
# =============================================================================
with qa_tab:
    top = st.columns([6, 1])
    top[0].caption("Answers come only from AtliQ's signed contracts, negotiation and meeting notes, principles and the commitments register. Not legal advice.")
    if top[1].button("🧹 Clear chat", use_container_width=True):
        state.chat = []
        st.rerun()

    for message in state.chat:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("sources"):
                with st.expander("Sources"):
                    for source in message["sources"]:
                        st.caption(source)

    question = st.chat_input("e.g. What have we promised Al Noor?")
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Searching AtliQ's contracts…"):
                try:
                    answer = qa.ask(question, [m for m in state.chat])
                except MissingKeyError as error:
                    st.error(str(error))
                    st.stop()
                except Exception as error:
                    st.error(f"The assistant is temporarily unavailable: {error}")
                    st.stop()
        state.chat.append({"role": "user", "content": question})
        state.chat.append({"role": "assistant", "content": answer.text, "sources": answer.sources})
        st.rerun()
