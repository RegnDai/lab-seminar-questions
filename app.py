import calendar
import hashlib
import hmac
import re
from collections import Counter
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import create_client


st.set_page_config(
    page_title="实验室组会提问板",
    page_icon="💬",
    layout="wide",
)


APP_TIMEZONE = st.secrets.get("APP_TIMEZONE", "Asia/Shanghai")

QUESTION_TAGS = [
    "实验设计",
    "样本/分组",
    "统计模型",
    "参数/阈值",
    "数据处理",
    "结果解释",
    "机制追问",
    "验证实验",
    "文献背景",
    "应用价值",
    "表达澄清",
    "其他",
]

REACTION_TYPES = [
    "🧠批判性思维",
    "💡还有这种思路",
    "🤝英雄所见略同",
    "🔍严谨审视",
    "✨很有启发",
]

AWARD_TITLES = {
    "🧠批判性思维": "批判性思考者",
    "💡还有这种思路": "创想者",
    "🤝英雄所见略同": "大众嘴替",
    "🔍严谨审视": "严谨者",
    "✨很有启发": "启迪者",
}

REACTION_ALIASES = {
    "🧠 批判性思维": "🧠批判性思维",
    "💡 还有这种思路": "💡还有这种思路",
    "🤝 英雄所见略同": "🤝英雄所见略同",
    "🔍 严谨审视": "🔍严谨审视",
    "✨ 很有启发": "✨很有启发",
    "批判性思维": "🧠批判性思维",
    "还有这种思路": "💡还有这种思路",
    "英雄所见略同": "🤝英雄所见略同",
    "严谨审视": "🔍严谨审视",
    "很有启发": "✨很有启发",
    "有启发": "✨很有启发",
}


@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SERVICE_ROLE_KEY"],
    )


supabase = get_supabase()


def get_now_local():
    return datetime.now(ZoneInfo(APP_TIMEZONE))


def clean_text(value) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    value = str(value).strip()

    if value.lower() in ["nan", "none", "nat"]:
        return ""

    return value


def normalize_reaction_type(value: str) -> str:
    value = clean_text(value)

    if not value:
        return "✨很有启发"

    value = REACTION_ALIASES.get(value, value)

    if value not in REACTION_TYPES:
        return "✨很有启发"

    return value


def get_members() -> list[str]:
    return list(st.secrets.get("MEMBERS", []))


def get_member_passwords() -> dict[str, str]:
    raw = st.secrets.get("MEMBER_PASSWORDS", {})

    try:
        return {str(k): str(v) for k, v in dict(raw).items()}
    except Exception:
        return {}


def check_password(input_value: str, secret_value: str) -> bool:
    return hmac.compare_digest(str(input_value), str(secret_value))


def check_member_login(name: str, password: str) -> bool:
    passwords = get_member_passwords()
    expected = passwords.get(str(name), "")

    if not expected:
        return False

    return check_password(
        str(password).strip().lower(),
        str(expected).strip().lower(),
    )


def clear_caches():
    load_meetings.clear()
    load_talks.clear()
    load_questions.clear()
    load_votes.clear()


@st.cache_data(ttl=5)
def load_meetings() -> pd.DataFrame:
    response = (
        supabase.table("seminar_meetings")
        .select("*")
        .order("meeting_date", desc=True)
        .order("id", desc=True)
        .limit(200)
        .execute()
    )

    df = pd.DataFrame(response.data or [])

    if df.empty:
        return pd.DataFrame(columns=["id", "meeting_date", "title", "status", "created_at"])

    df["meeting_date"] = pd.to_datetime(df["meeting_date"], errors="coerce").dt.date
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")

    return df


@st.cache_data(ttl=5)
def load_talks(meeting_id: int) -> pd.DataFrame:
    response = (
        supabase.table("seminar_talks")
        .select("*")
        .eq("meeting_id", int(meeting_id))
        .order("sort_order", desc=False)
        .order("id", desc=False)
        .limit(500)
        .execute()
    )

    df = pd.DataFrame(response.data or [])

    if df.empty:
        return pd.DataFrame(
            columns=[
                "id",
                "meeting_id",
                "speaker_name",
                "talk_title",
                "talk_type",
                "requires_question",
                "sort_order",
                "created_at",
            ]
        )

    df["sort_order"] = pd.to_numeric(df["sort_order"], errors="coerce").fillna(0).astype(int)
    df["requires_question"] = df["requires_question"].fillna(False).astype(bool)

    return df


@st.cache_data(ttl=5)
def load_questions(meeting_id: int | None = None) -> pd.DataFrame:
    query = supabase.table("seminar_questions").select("*")

    if meeting_id is not None:
        query = query.eq("meeting_id", int(meeting_id))

    response = (
        query
        .order("created_at", desc=False)
        .limit(5000)
        .execute()
    )

    df = pd.DataFrame(response.data or [])

    if df.empty:
        return pd.DataFrame(
            columns=[
                "id",
                "meeting_id",
                "talk_id",
                "asker_name",
                "context_label",
                "question_text",
                "question_tag",
                "answer_text",
                "answer_by",
                "is_asked_live",
                "is_featured",
                "created_at",
                "answered_at",
            ]
        )

    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["answered_at"] = pd.to_datetime(df["answered_at"], errors="coerce")
    df["is_asked_live"] = df["is_asked_live"].fillna(False).astype(bool)
    df["is_featured"] = df["is_featured"].fillna(False).astype(bool)

    return df


@st.cache_data(ttl=5)
def load_votes() -> pd.DataFrame:
    response = (
        supabase.table("seminar_question_votes")
        .select("*")
        .order("created_at", desc=False)
        .limit(50000)
        .execute()
    )

    df = pd.DataFrame(response.data or [])

    if df.empty:
        return pd.DataFrame(columns=["id", "question_id", "voter_name", "reaction_type", "created_at"])

    if "reaction_type" not in df.columns:
        df["reaction_type"] = "有启发"

    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["reaction_type"] = df["reaction_type"].fillna("有启发").astype(str)

    return df


def create_meeting(meeting_date, title: str):
    supabase.table("seminar_meetings").insert(
        {
            "meeting_date": meeting_date.isoformat(),
            "title": title.strip(),
            "status": "open",
        }
    ).execute()
    clear_caches()


def update_meeting_status(meeting_id: int, status: str):
    supabase.table("seminar_meetings").update(
        {"status": status}
    ).eq("id", int(meeting_id)).execute()
    clear_caches()


def add_blank_talk(meeting_id: int, user_name: str):
    talks = load_talks(meeting_id)
    next_order = int(talks["sort_order"].max() + 1) if not talks.empty else 1

    supabase.table("seminar_talks").insert(
        {
            "meeting_id": int(meeting_id),
            "speaker_name": user_name,
            "talk_title": "",
            "talk_type": "update",
            "requires_question": False,
            "sort_order": next_order,
        }
    ).execute()
    clear_caches()


def update_talk(
    talk_id: int,
    speaker_name: str,
    talk_title: str,
    talk_type: str,
    requires_question: bool,
    sort_order: int,
):
    supabase.table("seminar_talks").update(
        {
            "speaker_name": speaker_name.strip(),
            "talk_title": talk_title.strip(),
            "talk_type": talk_type,
            "requires_question": bool(requires_question),
            "sort_order": int(sort_order),
        }
    ).eq("id", int(talk_id)).execute()
    clear_caches()


def create_question(
    meeting_id: int,
    talk_id: int,
    asker_name: str,
    context_label: str,
    question_text: str,
    question_tag: str | None,
):
    supabase.table("seminar_questions").insert(
        {
            "meeting_id": int(meeting_id),
            "talk_id": int(talk_id),
            "asker_name": asker_name,
            "context_label": context_label.strip() or None,
            "question_text": question_text.strip(),
            "question_tag": question_tag or None,
        }
    ).execute()
    clear_caches()


def vote_question(question_id: int, voter_name: str, reaction_type: str) -> bool:
    try:
        supabase.table("seminar_question_votes").insert(
            {
                "question_id": int(question_id),
                "voter_name": voter_name,
                "reaction_type": reaction_type,
            }
        ).execute()
        clear_caches()
        return True
    except Exception:
        return False


def update_question_answer(question_id: int, answer_text: str, answer_by: str):
    supabase.table("seminar_questions").update(
        {
            "answer_text": answer_text.strip() or None,
            "answer_by": answer_by.strip() or None,
            "answered_at": get_now_local().isoformat() if answer_text.strip() else None,
        }
    ).eq("id", int(question_id)).execute()
    clear_caches()


def update_question_flags(question_id: int, is_asked_live: bool | None = None, is_featured: bool | None = None):
    payload = {}

    if is_asked_live is not None:
        payload["is_asked_live"] = bool(is_asked_live)

    if is_featured is not None:
        payload["is_featured"] = bool(is_featured)

    if payload:
        supabase.table("seminar_questions").update(payload).eq("id", int(question_id)).execute()
        clear_caches()



def update_question_admin(
    question_id: int,
    asker_name: str,
    context_label: str,
    question_text: str,
    question_tag: str | None,
    answer_text: str,
    answer_by: str,
    is_featured: bool,
):
    payload = {
        "asker_name": asker_name.strip(),
        "context_label": context_label.strip() or None,
        "question_text": question_text.strip(),
        "question_tag": question_tag or None,
        "answer_text": answer_text.strip() or None,
        "answer_by": answer_by.strip() or None,
        "answered_at": get_now_local().isoformat() if answer_text.strip() else None,
        "is_featured": bool(is_featured),
    }

    supabase.table("seminar_questions").update(payload).eq("id", int(question_id)).execute()
    clear_caches()


def delete_question_admin(question_id: int):
    # seminar_question_votes 有 on delete cascade，所以删问题时点赞会自动删除
    supabase.table("seminar_questions").delete().eq("id", int(question_id)).execute()
    clear_caches()


def month_label_from_date(value) -> str:
    dt = pd.to_datetime(value, errors="coerce")

    if pd.isna(dt):
        return ""

    return dt.to_period("M").strftime("%Y-%m")


def collect_talks_for_meetings(meeting_ids: list[int]) -> pd.DataFrame:
    frames = []

    for meeting_id in meeting_ids:
        df = load_talks(int(meeting_id))
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame(
            columns=[
                "id",
                "meeting_id",
                "speaker_name",
                "talk_title",
                "talk_type",
                "requires_question",
                "sort_order",
                "created_at",
            ]
        )

    return pd.concat(frames, ignore_index=True)



def meeting_display(row) -> str:
    return f"{row['meeting_date']}｜{row['title']}｜{row['status']}"


def talk_type_label(value: str) -> str:
    return {
        "main": "主讲 / Journal Club",
        "update": "简短工作汇报",
        "other": "其他",
    }.get(value, value)


def render_login():
    st.title("💬 实验室组会提问板")
    st.caption("一个组会现场页：添加汇报模块，然后在模块下提问、回复、点赞。")

    if "member_ok" not in st.session_state:
        st.session_state.member_ok = False

    if "current_user_name" not in st.session_state:
        st.session_state.current_user_name = ""

    if st.session_state.member_ok:
        return st.session_state.current_user_name

    members = get_members()

    if not members:
        st.error("还没有配置 MEMBERS。")
        st.stop()

    st.info("请选择姓名并输入个人密码。密码默认为姓名全拼，例如 zhaoyang、daiyuchi。")

    login_name = st.selectbox("姓名", members, key="login_name")
    login_password = st.text_input("个人密码", type="password", key="login_password")

    if st.button("进入", type="primary"):
        if check_member_login(login_name, login_password):
            st.session_state.member_ok = True
            st.session_state.current_user_name = login_name
            st.rerun()
        else:
            st.error("姓名或密码不对。")

    st.stop()


def render_question(
    question,
    votes_for_question: pd.DataFrame,
    has_reacted: bool,
    user_name: str,
    speaker_name: str,
):
    question_id = int(question["id"])

    asker = clean_text(question.get("asker_name"))
    context = clean_text(question.get("context_label"))
    tag = clean_text(question.get("question_tag"))
    question_text = clean_text(question.get("question_text"))
    answer_text = clean_text(question.get("answer_text"))
    answer_by = clean_text(question.get("answer_by"))

    is_own_question = clean_text(user_name) == clean_text(asker)
    is_speaker = clean_text(user_name) == clean_text(speaker_name)

    flags = []

    if context:
        flags.append(context)

    if tag:
        flags.append(tag)

    if bool(question.get("is_featured")):
        flags.append("🌟 主讲人觉得很赞")

    st.markdown(f"**{asker}**：{question_text}")

    if flags:
        st.caption(" · ".join(flags))

    def _normalize_reaction(value: str) -> str:
        value = clean_text(value)

        aliases = {
            "🧠 批判性思维": "🧠批判性思维",
            "💡 还有这种思路": "💡还有这种思路",
            "🤝 英雄所见略同": "🤝英雄所见略同",
            "🔍 严谨审视": "🔍严谨审视",
            "✨ 很有启发": "✨很有启发",
            "批判性思维": "🧠批判性思维",
            "还有这种思路": "💡还有这种思路",
            "英雄所见略同": "🤝英雄所见略同",
            "严谨审视": "🔍严谨审视",
            "很有启发": "✨很有启发",
            "有启发": "✨很有启发",
        }

        value = aliases.get(value, value)

        if value not in REACTION_TYPES:
            return "✨很有启发"

        return value

    reaction_counts = {}

    if not votes_for_question.empty:
        tmp = votes_for_question.copy()
        tmp["reaction_type"] = tmp["reaction_type"].apply(_normalize_reaction)
        reaction_counts = tmp["reaction_type"].value_counts().to_dict()

    if answer_text:
        st.markdown(f"> **{answer_by or '回复'}：** {answer_text}")

    reaction_cols = st.columns([1.45, 1.55, 1.65, 1.35, 1.35, 1.15])

    for idx, reaction_type in enumerate(REACTION_TYPES):
        count = int(reaction_counts.get(reaction_type, 0))

        with reaction_cols[idx]:
            if st.button(
                f"{reaction_type} {count}",
                key=f"reaction_{question_id}_{idx}_{user_name}",
                disabled=has_reacted or is_own_question,
            ):
                ok = vote_question(question_id, user_name, reaction_type)

                if not ok:
                    st.info("你已经给这条问题标注过反应。")

                st.rerun()

    with reaction_cols[5]:
        can_speaker_endorse = is_speaker and not is_own_question

        if can_speaker_endorse:
            endorse_label = "🌟 主讲已赞" if bool(question.get("is_featured")) else "🌟 主讲赞"

            if st.button(endorse_label, key=f"speaker_endorse_{question_id}"):
                update_question_flags(
                    question_id,
                    is_featured=not bool(question.get("is_featured")),
                )
                st.rerun()
        else:
            st.button(
                "🌟 主讲已赞" if bool(question.get("is_featured")) else "🌟 主讲赞",
                key=f"speaker_endorse_disabled_{question_id}",
                disabled=True,
            )

    if is_own_question:
        st.caption("不能评价自己的问题。")
    elif has_reacted:
        st.caption("你已经给这条问题标注过一个反应。")

    with st.expander("回复"):
        with st.form(f"answer_form_{question_id}"):
            answer_by_input = st.text_input(
                "回复人",
                value=answer_by or user_name,
                key=f"answer_by_{question_id}",
            )
            answer_text_input = st.text_area(
                "回答",
                value=answer_text,
                height=100,
                key=f"answer_text_{question_id}",
            )
            if st.form_submit_button("保存回复"):
                update_question_answer(question_id, answer_text_input, answer_by_input)
                st.rerun()

    st.divider()



def render_talk_module(meeting, talk, questions, votes, user_name: str):
    talk_id = int(talk["id"])
    speaker = clean_text(talk.get("speaker_name")) or "未填写汇报人"
    title = clean_text(talk.get("talk_title")) or "未填写主题"
    talk_type = clean_text(talk.get("talk_type")) or "update"

    question_count = len(questions[questions["talk_id"].astype(str) == str(talk_id)])

    st.markdown(f"## {talk['sort_order']}. {speaker}")
    st.markdown(f"**{title}**")
    st.caption(f"{talk_type_label(talk_type)} · {question_count} 个问题")

    with st.expander("编辑这个汇报模块", expanded=not clean_text(talk.get("talk_title"))):
        with st.form(f"edit_talk_{talk_id}"):
            members = get_members()

            if members:
                default_index = members.index(speaker) if speaker in members else 0
                speaker_input = st.selectbox(
                    "汇报人",
                    members,
                    index=default_index,
                    key=f"speaker_{talk_id}",
                )
            else:
                speaker_input = st.text_input(
                    "汇报人",
                    value=speaker if speaker != "未填写汇报人" else "",
                    key=f"speaker_{talk_id}",
                )

            title_input = st.text_input(
                "汇报主题",
                value=clean_text(talk.get("talk_title")),
                placeholder="例如：某篇文献 / 项目进展 / 数据结果讨论",
                key=f"title_{talk_id}",
            )

            type_input = st.selectbox(
                "环节类型",
                ["main", "update", "other"],
                index=["main", "update", "other"].index(talk_type) if talk_type in ["main", "update", "other"] else 1,
                format_func=talk_type_label,
                key=f"type_{talk_id}",
            )

            requires_input = st.checkbox(
                "这个环节要求每个人至少提 1 个问题",
                value=bool(talk.get("requires_question")),
                key=f"requires_{talk_id}",
            )

            order_input = st.number_input(
                "排序",
                min_value=0,
                max_value=999,
                value=int(talk.get("sort_order") or 0),
                step=1,
                key=f"order_{talk_id}",
            )

            if st.form_submit_button("保存汇报信息", type="primary"):
                if not clean_text(speaker_input):
                    st.error("汇报人不能为空。")
                else:
                    update_talk(
                        talk_id=talk_id,
                        speaker_name=speaker_input,
                        talk_title=title_input,
                        talk_type=type_input,
                        requires_question=requires_input,
                        sort_order=order_input,
                    )
                    st.rerun()

    scratch_key = f"scratch_{meeting['id']}_{talk_id}_{user_name}"

    st.text_area(
        "我的草稿本",
        key=scratch_key,
        height=130,
        placeholder="这里完全自由。你想写第几页 PPT、哪个图、哪些问题、哪些吐槽都可以。不公开，不计入统计。",
    )

    with st.form(f"ask_question_{talk_id}_{user_name}", clear_on_submit=True):
        context = st.text_input(
            "上下文，可选",
            placeholder="P12 / 图3 / 表2 / 口头讨论",
            key=f"context_{talk_id}_{user_name}",
        )

        question_text = st.text_area(
            "发布问题",
            height=100,
            placeholder="把你想公开提问的内容写在这里。发布后会进入评论区。",
            key=f"question_text_{talk_id}_{user_name}",
        )

        tag = st.selectbox(
            "问题标签，可选",
            [None] + QUESTION_TAGS,
            format_func=lambda x: "不选择" if x is None else x,
            key=f"tag_{talk_id}_{user_name}",
        )

        if st.form_submit_button("发布问题", type="primary"):
            if not clean_text(question_text):
                st.error("问题不能为空。")
            else:
                create_question(
                    meeting_id=int(meeting["id"]),
                    talk_id=talk_id,
                    asker_name=user_name,
                    context_label=context,
                    question_text=question_text,
                    question_tag=tag,
                )
                st.rerun()

    st.markdown("### 问题区")

    talk_questions = questions[questions["talk_id"].astype(str) == str(talk_id)].copy()

    if talk_questions.empty:
        st.info("还没有问题。")
        return

    user_reacted = set(
        votes[votes["voter_name"].astype(str) == str(user_name)]["question_id"].astype(int).tolist()
        if not votes.empty
        else []
    )

    talk_questions = talk_questions.sort_values(
        ["is_featured", "created_at"],
        ascending=[False, True],
    )

    for _, question in talk_questions.iterrows():
        qid = int(question["id"])

        votes_for_question = (
            votes[votes["question_id"].astype(int) == qid].copy()
            if not votes.empty
            else pd.DataFrame(columns=["reaction_type"])
        )

        render_question(
            question=question,
            votes_for_question=votes_for_question,
            has_reacted=qid in user_reacted,
            user_name=user_name,
            speaker_name=speaker,
        )


def render_live_page(user_name: str):
    st.markdown("<div id='seminar-live-top'></div>", unsafe_allow_html=True)
    st.header("组会现场")

    with st.sidebar:
        st.success(f"当前用户：{user_name}")

        if st.button("切换身份"):
            st.session_state.member_ok = False
            st.session_state.current_user_name = ""
            st.rerun()

    meetings = load_meetings()

    with st.expander("组会设置", expanded=meetings.empty):
        with st.form("create_meeting_form"):
            meeting_date = st.date_input("组会日期", value=get_now_local().date())
            meeting_title = st.text_input("组会标题", value=f"{get_now_local().date()} 实验室组会")

            if st.form_submit_button("创建组会", type="primary"):
                if not clean_text(meeting_title):
                    st.error("组会标题不能为空。")
                else:
                    create_meeting(meeting_date, meeting_title)
                    st.rerun()

    meetings = load_meetings()

    if meetings.empty:
        st.info("先创建一次组会。")
        return

    selected_meeting_id = st.selectbox(
        "当前组会",
        meetings["id"].tolist(),
        format_func=lambda x: meeting_display(meetings[meetings["id"] == x].iloc[0]),
        key="current_meeting_select",
    )

    meeting = meetings[meetings["id"] == selected_meeting_id].iloc[0].to_dict()

    c1, c2, c3 = st.columns([3, 1, 1])

    with c1:
        st.subheader(f"{meeting['meeting_date']}｜{meeting['title']}")

    with c2:
        if st.button("设为开放", disabled=meeting["status"] == "open"):
            update_meeting_status(int(meeting["id"]), "open")
            st.rerun()

    with c3:
        if st.button("设为关闭", disabled=meeting["status"] == "closed"):
            update_meeting_status(int(meeting["id"]), "closed")
            st.rerun()

    st.caption("谁要汇报，就按下面的加号添加一个汇报模块，然后自己填写信息。其他人直接在对应模块下提问。")

    st.markdown("<div id='add-talk-module'></div>", unsafe_allow_html=True)

    if st.button("＋ 添加汇报模块", type="primary"):
        add_blank_talk(int(meeting["id"]), user_name)
        st.rerun()

    talks = load_talks(int(meeting["id"]))
    questions = load_questions(int(meeting["id"]))
    votes = load_votes()

    if talks.empty:
        st.info("还没有汇报模块。")
        return

    with st.sidebar:
        st.divider()
        st.subheader("快速导航")
        st.caption("点击跳到对应位置。")

        st.markdown("- [＋ 添加汇报模块](#seminar-live-top)")

        for _, talk in talks.iterrows():
            talk_id = int(talk["id"])
            speaker = clean_text(talk.get("speaker_name")) or "未填写汇报人"
            title = clean_text(talk.get("talk_title"))

            label = f"{int(talk.get('sort_order') or 0)}. {speaker}"
            if title:
                label += f"｜{title[:12]}"

            st.markdown(f"- [{label}](#talk-{talk_id})")

    for _, talk in talks.iterrows():
        talk_id = int(talk["id"])
        st.markdown(f"<div id='talk-{talk_id}'></div>", unsafe_allow_html=True)
        st.divider()
        render_talk_module(
            meeting=meeting,
            talk=talk,
            questions=questions,
            votes=votes,
            user_name=user_name,
        )



def clear_poll_caches():
    try:
        load_polls.clear()
        load_poll_options.clear()
        load_poll_votes.clear()
    except Exception:
        pass


@st.cache_data(ttl=5)
def load_polls() -> pd.DataFrame:
    response = (
        supabase.table("seminar_polls")
        .select("*")
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )

    df = pd.DataFrame(response.data or [])

    if df.empty:
        return pd.DataFrame(columns=["id", "title", "status", "created_by", "created_at"])

    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")

    return df


@st.cache_data(ttl=5)
def load_poll_options(poll_id: int | None = None) -> pd.DataFrame:
    query = supabase.table("seminar_poll_options").select("*")

    if poll_id is not None:
        query = query.eq("poll_id", int(poll_id))

    response = (
        query
        .order("id", desc=False)
        .limit(5000)
        .execute()
    )

    df = pd.DataFrame(response.data or [])

    if df.empty:
        return pd.DataFrame(columns=["id", "poll_id", "talk_id", "option_label", "created_at"])

    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")

    return df


@st.cache_data(ttl=5)
def load_poll_votes(poll_id: int | None = None) -> pd.DataFrame:
    query = supabase.table("seminar_poll_votes").select("*")

    if poll_id is not None:
        query = query.eq("poll_id", int(poll_id))

    response = (
        query
        .order("created_at", desc=False)
        .limit(50000)
        .execute()
    )

    df = pd.DataFrame(response.data or [])

    if df.empty:
        return pd.DataFrame(columns=["id", "poll_id", "option_id", "voter_hash", "created_at"])

    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")

    return df


def make_voter_hash(user_name: str, poll_id: int) -> str:
    salt = st.secrets.get("POLL_SALT", st.secrets.get("ADMIN_CODE", "seminar-poll-salt"))
    raw = f"{salt}|{poll_id}|{user_name}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def create_poll(title: str, options: list[dict], created_by: str):
    response = supabase.table("seminar_polls").insert(
        {
            "title": title.strip(),
            "status": "open",
            "created_by": created_by,
        }
    ).execute()

    poll_data = response.data or []

    if not poll_data:
        return

    poll_id = int(poll_data[0]["id"])

    rows = [
        {
            "poll_id": poll_id,
            "talk_id": int(item["talk_id"]),
            "option_label": item["option_label"],
        }
        for item in options
    ]

    if rows:
        supabase.table("seminar_poll_options").insert(rows).execute()

    clear_poll_caches()


def vote_poll(poll_id: int, option_id: int, user_name: str) -> bool:
    voter_hash = make_voter_hash(user_name, poll_id)

    try:
        supabase.table("seminar_poll_votes").insert(
            {
                "poll_id": int(poll_id),
                "option_id": int(option_id),
                "voter_hash": voter_hash,
            }
        ).execute()
        clear_poll_caches()
        return True
    except Exception:
        return False


def update_poll_status(poll_id: int, status: str):
    supabase.table("seminar_polls").update(
        {"status": status}
    ).eq("id", int(poll_id)).execute()

    clear_poll_caches()


def render_poll_page(user_name: str):
    st.header("匿名投票")
    st.caption("可以勾选某几次主讲，发起一次匿名投票，选出最佳汇报人。结果只显示票数，不显示投票人。")

    polls = load_polls()

    st.subheader("参与投票")

    if polls.empty:
        st.info("还没有投票。")
    else:
        selected_poll_id = st.selectbox(
            "选择投票",
            polls["id"].tolist(),
            format_func=lambda x: f"{polls[polls['id'] == x].iloc[0]['title']}｜{polls[polls['id'] == x].iloc[0]['status']}",
            key="poll_select",
        )

        poll = polls[polls["id"] == selected_poll_id].iloc[0].to_dict()
        options = load_poll_options(int(selected_poll_id))
        votes = load_poll_votes(int(selected_poll_id))

        if options.empty:
            st.info("这个投票没有候选项。")
        else:
            voter_hash = make_voter_hash(user_name, int(selected_poll_id))
            has_voted = False

            if not votes.empty:
                has_voted = voter_hash in votes["voter_hash"].astype(str).tolist()

            if poll["status"] == "open":
                if has_voted:
                    st.success("你已经投过票了。")
                else:
                    option_id = st.radio(
                        "选择你认为最好的汇报",
                        options["id"].tolist(),
                        format_func=lambda x: options[options["id"] == x].iloc[0]["option_label"],
                        key=f"poll_vote_radio_{selected_poll_id}",
                    )

                    if st.button("匿名投票", type="primary", key=f"vote_poll_{selected_poll_id}"):
                        ok = vote_poll(int(selected_poll_id), int(option_id), user_name)

                        if ok:
                            st.success("投票成功。")
                        else:
                            st.info("你已经投过票了。")

                        st.rerun()
            else:
                st.info("这个投票已经关闭。")

            st.subheader("当前结果")

            if votes.empty:
                result = options[["id", "option_label"]].copy()
                result["票数"] = 0
            else:
                counts = votes.groupby("option_id")["id"].count().reset_index(name="票数")
                result = options.merge(
                    counts,
                    left_on="id",
                    right_on="option_id",
                    how="left",
                ).fillna({"票数": 0})
                result["票数"] = result["票数"].astype(int)

            result = result[["option_label", "票数"]].rename(columns={"option_label": "候选汇报"})
            result = result.sort_values("票数", ascending=False)

            st.dataframe(result, use_container_width=True, hide_index=True)

            if st.session_state.get("admin_ok", False):
                c1, c2 = st.columns(2)

                with c1:
                    if st.button("开放投票", disabled=poll["status"] == "open", key=f"open_poll_{selected_poll_id}"):
                        update_poll_status(int(selected_poll_id), "open")
                        st.rerun()

                with c2:
                    if st.button("关闭投票", disabled=poll["status"] == "closed", key=f"close_poll_{selected_poll_id}"):
                        update_poll_status(int(selected_poll_id), "closed")
                        st.rerun()

    st.divider()
    st.subheader("创建投票")

    if not st.session_state.get("admin_ok", False):
        admin_code = st.text_input("管理员口令", type="password", key="poll_admin_code")

        if st.button("进入投票管理", key="poll_admin_login"):
            expected = st.secrets.get("ADMIN_CODE", "")

            if expected and check_password(admin_code, expected):
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error("管理员口令不对。")

        return

    meetings = load_meetings()

    if meetings.empty:
        st.info("还没有组会，无法创建投票。")
        return

    selected_meeting_ids = st.multiselect(
        "选择候选汇报所在的组会",
        meetings["id"].tolist(),
        default=meetings["id"].head(1).tolist(),
        format_func=lambda x: meeting_display(meetings[meetings["id"] == x].iloc[0]),
        key="poll_meeting_multiselect",
    )

    if not selected_meeting_ids:
        st.info("先选择至少一次组会。")
        return

    candidate_talks = collect_talks_for_meetings([int(x) for x in selected_meeting_ids])

    if candidate_talks.empty:
        st.info("所选组会没有汇报模块。")
        return

    only_main = st.checkbox("只显示主讲 / Journal Club", value=True, key="poll_only_main")

    if only_main:
        candidate_talks = candidate_talks[candidate_talks["talk_type"] == "main"].copy()

    if candidate_talks.empty:
        st.info("没有符合条件的主讲。可以取消“只显示主讲 / Journal Club”。")
        return

    meeting_map = meetings.set_index("id")["meeting_date"].to_dict()

    def poll_talk_label(talk_id):
        row = candidate_talks[candidate_talks["id"] == talk_id].iloc[0]
        meeting_date = meeting_map.get(row["meeting_id"], "")
        speaker = clean_text(row.get("speaker_name"))
        title = clean_text(row.get("talk_title"))
        return f"{meeting_date}｜{speaker}｜{title or talk_type_label(row.get('talk_type'))}"

    selected_talk_ids = st.multiselect(
        "勾选参与投票的主讲",
        candidate_talks["id"].astype(int).tolist(),
        format_func=poll_talk_label,
        key="poll_talk_multiselect",
    )

    with st.form("create_poll_form"):
        poll_title = st.text_input(
            "投票标题",
            value=f"{get_now_local().date()} 最佳汇报人匿名投票",
        )

        submitted = st.form_submit_button("创建匿名投票", type="primary")

        if submitted:
            if not clean_text(poll_title):
                st.error("投票标题不能为空。")
            elif not selected_talk_ids:
                st.error("至少勾选一个主讲。")
            else:
                options = [
                    {
                        "talk_id": int(talk_id),
                        "option_label": poll_talk_label(int(talk_id)),
                    }
                    for talk_id in selected_talk_ids
                ]

                create_poll(poll_title, options, user_name)
                st.success("投票已创建。")
                st.rerun()



def render_calendar_page():
    st.header("组会日历")

    meetings = load_meetings()

    if meetings.empty:
        st.info("暂无组会。")
        return

    meetings = meetings.copy()
    meetings["month"] = meetings["meeting_date"].apply(month_label_from_date)

    available_months = sorted(
        [x for x in meetings["month"].dropna().unique().tolist() if x],
        reverse=True,
    )

    current_month = get_now_local().strftime("%Y-%m")

    if current_month not in available_months:
        available_months = [current_month] + available_months

    selected_month = st.selectbox(
        "选择月份",
        available_months,
        index=0,
        key="calendar_month_select",
    )

    year, month = map(int, selected_month.split("-"))

    month_meetings = meetings[meetings["month"] == selected_month].copy()
    meeting_ids = month_meetings["id"].astype(int).tolist()

    all_questions = load_questions(None)

    if not all_questions.empty and meeting_ids:
        q_counts = (
            all_questions[all_questions["meeting_id"].isin(meeting_ids)]
            .groupby("meeting_id")["id"]
            .count()
            .to_dict()
        )
    else:
        q_counts = {}

    st.subheader(f"{year} 年 {month} 月")

    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdayscalendar(year, month)
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    header_cols = st.columns(7)
    for col, name in zip(header_cols, weekday_names):
        col.markdown(f"**{name}**")

    for week in weeks:
        cols = st.columns(7)

        for col, day in zip(cols, week):
            if day == 0:
                col.write("")
                continue

            day_date = pd.Timestamp(year=year, month=month, day=day).date()
            day_meetings = month_meetings[month_meetings["meeting_date"] == day_date]

            with col:
                st.markdown(f"### {day}")

                if day_meetings.empty:
                    st.caption(" ")
                else:
                    for _, row in day_meetings.iterrows():
                        mid = int(row["id"])
                        title = clean_text(row.get("title"))
                        status = clean_text(row.get("status"))
                        count = int(q_counts.get(mid, 0))

                        st.markdown(f"**{title}**")
                        st.caption(f"{status} · {count} 个问题")

    st.divider()

    st.subheader("本月组会列表")

    if month_meetings.empty:
        st.info("这个月还没有组会。")
    else:
        rows = []

        for _, row in month_meetings.sort_values("meeting_date").iterrows():
            rows.append(
                {
                    "日期": row["meeting_date"],
                    "组会": clean_text(row.get("title")),
                    "状态": clean_text(row.get("status")),
                    "问题数": int(q_counts.get(int(row["id"]), 0)),
                }
            )

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_stats_page():
    st.header("统计评选")

    meetings = load_meetings()

    if meetings.empty:
        st.info("暂无组会。")
        return

    meetings = meetings.copy()
    meetings["month"] = meetings["meeting_date"].apply(month_label_from_date)

    available_months = sorted(
        [x for x in meetings["month"].dropna().unique().tolist() if x],
        reverse=True,
    )

    if not available_months:
        st.info("暂无可统计月份。")
        return

    use_all_months = st.checkbox("统计全部月份", value=False)

    if use_all_months:
        selected_months = available_months
    else:
        selected_months = st.multiselect(
            "选择统计月份",
            available_months,
            default=[available_months[0]],
            key="stats_month_multiselect",
        )

    if not selected_months:
        st.warning("至少选择一个月份。")
        return

    selected_meetings = meetings[meetings["month"].isin(selected_months)].copy()
    meeting_ids = selected_meetings["id"].astype(int).tolist()

    if not meeting_ids:
        st.info("所选月份没有组会。")
        return

    all_questions = load_questions(None)
    questions = all_questions[all_questions["meeting_id"].isin(meeting_ids)].copy()

    talks = collect_talks_for_meetings(meeting_ids)
    votes = load_votes()

    if questions.empty:
        st.info("所选月份还没有问题。")
        return

    questions["is_featured"] = questions["is_featured"].fillna(False).astype(bool)

    selected_question_ids = questions["id"].astype(int).tolist()

    if votes.empty:
        selected_votes = pd.DataFrame(columns=["id", "question_id", "voter_name", "reaction_type", "created_at"])
    else:
        selected_votes = votes[votes["question_id"].astype(int).isin(selected_question_ids)].copy()

    if not selected_votes.empty:
        selected_votes["reaction_type"] = selected_votes["reaction_type"].apply(normalize_reaction_type)

    # 每条 vote 归属到被提问者
    if selected_votes.empty:
        vote_rows = pd.DataFrame(columns=["question_id", "asker_name", "reaction_type"])
    else:
        vote_rows = selected_votes.merge(
            questions[["id", "asker_name", "meeting_id"]],
            left_on="question_id",
            right_on="id",
            how="left",
        )

    reaction_columns = list(REACTION_TYPES)

    # 提问数
    question_counts = (
        questions.groupby("asker_name", as_index=False)
        .agg(提问数=("id", "count"))
        .rename(columns={"asker_name": "姓名"})
    )

    # 主讲人赞数：沿用数据库 is_featured 字段
    speaker_stars = (
        questions.groupby("asker_name", as_index=False)
        .agg(主讲人赞数=("is_featured", "sum"))
        .rename(columns={"asker_name": "姓名"})
    )

    # 回复数：answer_text 非空，按 answer_by 统计
    answered_questions = questions[
        questions["answer_text"].apply(clean_text).astype(bool)
        & questions["answer_by"].apply(clean_text).astype(bool)
    ].copy()

    if answered_questions.empty:
        answer_counts = pd.DataFrame(columns=["姓名", "回复数"])
    else:
        answer_counts = (
            answered_questions.groupby("answer_by", as_index=False)
            .agg(回复数=("id", "count"))
            .rename(columns={"answer_by": "姓名"})
        )

    # emoji 分项统计
    if vote_rows.empty:
        emoji_by_person = pd.DataFrame(columns=["姓名"] + reaction_columns)
    else:
        emoji_by_person = (
            vote_rows
            .pivot_table(
                index="asker_name",
                columns="reaction_type",
                values="question_id",
                aggfunc="count",
                fill_value=0,
            )
            .reset_index()
            .rename(columns={"asker_name": "姓名"})
        )

    all_names = sorted(
        set(question_counts["姓名"].astype(str).tolist())
        | set(speaker_stars["姓名"].astype(str).tolist())
        | set(answer_counts["姓名"].astype(str).tolist())
        | (set(emoji_by_person["姓名"].astype(str).tolist()) if not emoji_by_person.empty else set())
    )

    leaderboard = pd.DataFrame({"姓名": all_names})

    leaderboard = leaderboard.merge(question_counts, on="姓名", how="left")
    leaderboard = leaderboard.merge(speaker_stars, on="姓名", how="left")
    leaderboard = leaderboard.merge(answer_counts, on="姓名", how="left")
    leaderboard = leaderboard.merge(emoji_by_person, on="姓名", how="left")

    for col in ["提问数", "主讲人赞数", "回复数"] + reaction_columns:
        if col not in leaderboard.columns:
            leaderboard[col] = 0
        leaderboard[col] = leaderboard[col].fillna(0).astype(int)

    leaderboard["emoji总反应"] = leaderboard[reaction_columns].sum(axis=1).astype(int)
    leaderboard["提问大师分"] = (leaderboard["emoji总反应"] + leaderboard["主讲人赞数"]).astype(int)

    leaderboard = leaderboard.sort_values(
        ["提问大师分", "主讲人赞数", "emoji总反应", "提问数"],
        ascending=False,
    )

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric("统计月份", len(selected_months))

    with c2:
        st.metric("组会数", len(selected_meetings))

    with c3:
        st.metric("问题数", len(questions))

    with c4:
        st.metric("emoji反应", int(leaderboard["emoji总反应"].sum()))

    st.caption("当前统计范围：" + "、".join(selected_months))
    st.caption("提问大师分 = 五类 emoji 反应总数 + 主讲人赞数。暂不加权。")

    def get_winner(df: pd.DataFrame, col: str):
        if df.empty or col not in df.columns:
            return "暂无", "0 次"

        max_value = int(df[col].max())

        if max_value <= 0:
            return "暂无", "0 次"

        winners = df[df[col] == max_value]["姓名"].astype(str).tolist()
        shown = "、".join(winners[:3])

        if len(winners) > 3:
            shown += "等"

        return shown, f"{max_value} 次"

    st.subheader("本期称号")

    award_items = [
        ("📣 问题发动机", "提问数", "提出问题最多，最能把讨论启动起来"),
        ("🧠 批判性思考者", "🧠批判性思维", "最常被认为问出了批判性问题"),
        ("💡 创想者", "💡还有这种思路", "最常提出让人眼前一亮的思路"),
        ("🤝 大众嘴替", "🤝英雄所见略同", "最常问出大家心里也想问的问题"),
        ("🔍 严谨者", "🔍严谨审视", "最常抓住方法、证据和细节"),
        ("✨ 启迪者", "✨很有启发", "最常让别人觉得有启发"),
        ("🌟 主讲赏识奖", "主讲人赞数", "最常被主讲人认可为好问题"),
        ("💬 有问必答", "回复数", "回复问题最多，最愿意把讨论接住"),
        ("🏆 提问大师", "提问大师分", "综合表现最高"),
    ]

    award_cols = st.columns(3)

    for i, (title, col_name, caption) in enumerate(award_items):
        winner, score = get_winner(leaderboard, col_name)

        with award_cols[i % 3]:
            st.metric(title, winner, score)
            st.caption(caption)

    st.subheader("提问榜")

    display_cols = [
        "姓名",
        "提问数",
        "🧠批判性思维",
        "💡还有这种思路",
        "🤝英雄所见略同",
        "🔍严谨审视",
        "✨很有启发",
        "emoji总反应",
        "主讲人赞数",
        "回复数",
        "提问大师分",
    ]

    st.dataframe(
        leaderboard[display_cols],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("按月份统计")

    q_with_meeting = questions.merge(
        meetings[["id", "meeting_date", "month", "title"]],
        left_on="meeting_id",
        right_on="id",
        how="left",
        suffixes=("", "_meeting"),
    )

    by_month_base = (
        q_with_meeting.groupby("month", as_index=False)
        .agg(
            问题数=("id", "count"),
            提问人数=("asker_name", "nunique"),
            主讲人赞数=("is_featured", "sum"),
            回复数=("answer_text", lambda s: s.apply(clean_text).astype(bool).sum()),
        )
        .rename(columns={"month": "月份"})
    )

    if vote_rows.empty:
        by_month_emoji = pd.DataFrame(columns=["月份"] + reaction_columns)
    else:
        vote_with_month = vote_rows.merge(
            q_with_meeting[["id", "month"]],
            left_on="question_id",
            right_on="id",
            how="left",
        )

        by_month_emoji = (
            vote_with_month
            .pivot_table(
                index="month",
                columns="reaction_type",
                values="question_id",
                aggfunc="count",
                fill_value=0,
            )
            .reset_index()
            .rename(columns={"month": "月份"})
        )

    by_month = by_month_base.merge(by_month_emoji, on="月份", how="left")

    for col in reaction_columns:
        if col not in by_month.columns:
            by_month[col] = 0
        by_month[col] = by_month[col].fillna(0).astype(int)

    by_month["emoji总反应"] = by_month[reaction_columns].sum(axis=1).astype(int)
    by_month["主讲人赞数"] = by_month["主讲人赞数"].fillna(0).astype(int)
    by_month = by_month.sort_values("月份", ascending=False)

    st.dataframe(by_month, use_container_width=True, hide_index=True)

    if not talks.empty:
        matrix_source = questions.merge(
            talks[["id", "speaker_name"]],
            left_on="talk_id",
            right_on="id",
            how="left",
            suffixes=("", "_talk"),
        )

        matrix = matrix_source.pivot_table(
            index="speaker_name",
            columns="asker_name",
            values="id",
            aggfunc="count",
            fill_value=0,
        )

        matrix["合计"] = matrix.sum(axis=1)
        matrix = matrix.reset_index().rename(columns={"speaker_name": "汇报人"})

        st.subheader("汇报人 × 提问人矩阵")
        st.dataframe(matrix, use_container_width=True, hide_index=True)

    st.subheader("问题列表")

    if selected_votes.empty:
        emoji_by_question = pd.DataFrame(columns=["question_id"] + reaction_columns)
    else:
        emoji_by_question = (
            selected_votes
            .pivot_table(
                index="question_id",
                columns="reaction_type",
                values="id",
                aggfunc="count",
                fill_value=0,
            )
            .reset_index()
        )

    high = questions.merge(
        talks[["id", "speaker_name", "talk_title"]] if not talks.empty else pd.DataFrame(columns=["id", "speaker_name", "talk_title"]),
        left_on="talk_id",
        right_on="id",
        how="left",
        suffixes=("", "_talk"),
    )

    high = high.merge(
        meetings[["id", "meeting_date", "title"]],
        left_on="meeting_id",
        right_on="id",
        how="left",
        suffixes=("", "_meeting"),
    )

    high = high.merge(
        emoji_by_question,
        left_on="id",
        right_on="question_id",
        how="left",
    )

    for col in reaction_columns:
        if col not in high.columns:
            high[col] = 0
        high[col] = high[col].fillna(0).astype(int)

    high["emoji总反应"] = high[reaction_columns].sum(axis=1).astype(int)
    high["主讲人觉得很赞"] = high["is_featured"].fillna(False).astype(bool)

    high = high.sort_values(
        ["主讲人觉得很赞", "emoji总反应", "created_at"],
        ascending=[False, False, True],
    ).copy()

    rows = []

    for _, row in high.iterrows():
        rows.append(
            {
                "日期": row.get("meeting_date"),
                "组会": clean_text(row.get("title")),
                "汇报人": clean_text(row.get("speaker_name")),
                "提问人": clean_text(row.get("asker_name")),
                "上下文": clean_text(row.get("context_label")),
                "标签": clean_text(row.get("question_tag")),
                "问题": clean_text(row.get("question_text")),
                "🧠": int(row.get("🧠批判性思维", 0)),
                "💡": int(row.get("💡还有这种思路", 0)),
                "🤝": int(row.get("🤝英雄所见略同", 0)),
                "🔍": int(row.get("🔍严谨审视", 0)),
                "✨": int(row.get("✨很有启发", 0)),
                "emoji总反应": int(row.get("emoji总反应", 0)),
                "主讲人赞": "是" if bool(row.get("主讲人觉得很赞")) else "",
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)



def render_admin_page():
    st.header("管理员界面")
    st.caption("用于会后修正误提交、错别字、标签错误，或者删除无效问题。")

    if "admin_ok" not in st.session_state:
        st.session_state.admin_ok = False

    if not st.session_state.admin_ok:
        admin_code = st.text_input("管理员口令", type="password", key="admin_code_input")

        if st.button("进入管理员界面", type="primary"):
            expected = st.secrets.get("ADMIN_CODE", "")

            if not expected:
                st.error("secrets.toml 里还没有设置 ADMIN_CODE。")
            elif check_password(admin_code, expected):
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error("管理员口令不对。")

        st.stop()

    if st.button("退出管理员界面"):
        st.session_state.admin_ok = False
        st.rerun()

    meetings = load_meetings()

    if meetings.empty:
        st.info("暂无组会。")
        return

    selected_meeting_id = st.selectbox(
        "选择组会",
        meetings["id"].tolist(),
        format_func=lambda x: meeting_display(meetings[meetings["id"] == x].iloc[0]),
        key="admin_meeting_select",
    )

    talks = load_talks(int(selected_meeting_id))
    questions = load_questions(int(selected_meeting_id))

    if questions.empty:
        st.info("这次组会还没有问题。")
        return

    talk_map = {}

    if not talks.empty:
        for _, talk in talks.iterrows():
            speaker = clean_text(talk.get("speaker_name"))
            title = clean_text(talk.get("talk_title"))
            label = speaker

            if title:
                label += f"｜{title}"

            talk_map[int(talk["id"])] = label

    talk_filter_options = ["全部"] + [
        talk_map.get(int(tid), f"talk {tid}")
        for tid in questions["talk_id"].dropna().astype(int).unique().tolist()
    ]

    selected_talk_label = st.selectbox(
        "筛选汇报模块",
        talk_filter_options,
        key="admin_talk_filter",
    )

    q = questions.copy()

    if selected_talk_label != "全部":
        reverse_map = {v: k for k, v in talk_map.items()}
        selected_talk_id = reverse_map.get(selected_talk_label)

        if selected_talk_id is not None:
            q = q[q["talk_id"].astype(int) == int(selected_talk_id)]

    st.warning("删除问题不可恢复。确认是误提交、测试数据或明显无效内容后再删。")

    for _, question in q.sort_values("created_at", ascending=False).iterrows():
        question_id = int(question["id"])

        speaker_label = talk_map.get(int(question["talk_id"]), f"talk {question['talk_id']}")
        asker = clean_text(question.get("asker_name"))
        question_text = clean_text(question.get("question_text"))
        short_q = question_text[:42] + ("…" if len(question_text) > 42 else "")

        with st.expander(f"#{question_id}｜{speaker_label}｜{asker}：{short_q}"):
            with st.form(f"admin_edit_question_{question_id}"):
                members = get_members()

                if members:
                    if asker in members:
                        asker_index = members.index(asker)
                    else:
                        asker_index = 0

                    asker_input = st.selectbox(
                        "提问人",
                        members,
                        index=asker_index,
                        key=f"admin_asker_{question_id}",
                    )
                else:
                    asker_input = st.text_input(
                        "提问人",
                        value=asker,
                        key=f"admin_asker_{question_id}",
                    )

                context_input = st.text_input(
                    "上下文",
                    value=clean_text(question.get("context_label")),
                    key=f"admin_context_{question_id}",
                )

                question_input = st.text_area(
                    "问题内容",
                    value=question_text,
                    height=120,
                    key=f"admin_question_text_{question_id}",
                )

                current_tag = clean_text(question.get("question_tag"))
                tag_options = [None] + QUESTION_TAGS

                if current_tag and current_tag not in QUESTION_TAGS:
                    tag_options.append(current_tag)

                tag_index = tag_options.index(current_tag) if current_tag in tag_options else 0

                tag_input = st.selectbox(
                    "问题标签",
                    tag_options,
                    index=tag_index,
                    format_func=lambda x: "不选择" if x is None else x,
                    key=f"admin_tag_{question_id}",
                )

                answer_by_input = st.text_input(
                    "回复人",
                    value=clean_text(question.get("answer_by")),
                    key=f"admin_answer_by_{question_id}",
                )

                answer_input = st.text_area(
                    "回复内容",
                    value=clean_text(question.get("answer_text")),
                    height=100,
                    key=f"admin_answer_text_{question_id}",
                )

                st.caption(
                    "主讲人赞状态："
                    + ("主讲人已赞" if bool(question.get("is_featured")) else "主讲人未赞")
                    + "。这个状态只能由该汇报模块的主讲人在组会现场页操作。"
                )
                featured_input = bool(question.get("is_featured"))

                if st.form_submit_button("保存修改", type="primary"):
                    if not clean_text(asker_input):
                        st.error("提问人不能为空。")
                    elif not clean_text(question_input):
                        st.error("问题内容不能为空。")
                    else:
                        update_question_admin(
                            question_id=question_id,
                            asker_name=asker_input,
                            context_label=context_input,
                            question_text=question_input,
                            question_tag=tag_input,
                            answer_text=answer_input,
                            answer_by=answer_by_input,
                            is_featured=featured_input,
                        )
                        st.success("已保存修改。")
                        st.rerun()

            with st.form(f"admin_delete_question_{question_id}"):
                confirm = st.checkbox(
                    "确认删除这条问题",
                    key=f"admin_confirm_delete_{question_id}",
                )

                if st.form_submit_button("删除问题"):
                    if not confirm:
                        st.error("请先勾选确认删除。")
                    else:
                        delete_question_admin(question_id)
                        st.success("已删除问题。")
                        st.rerun()



WORD_CLOUD_STOPWORDS = {
    "这个", "那个", "这些", "那些", "一个", "一些", "一种", "我们", "你们", "他们",
    "是否", "什么", "为什么", "如何", "怎么", "可以", "可能", "需要", "应该",
    "因为", "所以", "但是", "如果", "然后", "以及", "或者", "还是", "没有",
    "进行", "通过", "对于", "关于", "里面", "时候", "比较", "感觉", "觉得",
    "问题", "提问", "回答", "汇报", "老师", "同学", "实验室",
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
}


def tokenize_for_wordcloud(text_value: str) -> list[str]:
    text_value = clean_text(text_value)

    if not text_value:
        return []

    # 保留中文、英文、数字，其余转为空格
    text_value = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9_]+", " ", text_value)

    try:
        import jieba
        raw_tokens = jieba.lcut(text_value)
    except Exception:
        raw_tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_]{1,}", text_value)

    tokens = []

    for token in raw_tokens:
        token = clean_text(token).lower()

        if not token:
            continue

        if token in WORD_CLOUD_STOPWORDS:
            continue

        if token.isdigit():
            continue

        # 中文单字基本没有信息量；英文至少 2 个字符
        if len(token) < 2:
            continue

        tokens.append(token)

    return tokens


def render_html_wordcloud(counter: Counter, max_words: int = 80):
    if not counter:
        st.info("没有足够的文本生成词云。")
        return

    items = counter.most_common(max_words)
    max_count = max(count for _, count in items)
    min_count = min(count for _, count in items)

    spans = []

    for word, count in items:
        safe_word = escape(str(word))
        safe_title = escape(f"{word}: {count}")

        if max_count == min_count:
            size = 24
        else:
            size = 14 + (count - min_count) / (max_count - min_count) * 30

        weight = 500 + min(350, count * 35)
        opacity = 0.58 + min(0.38, count / max_count * 0.38)

        spans.append(
            f"""
            <span
                title="{safe_title}"
                style="
                    display:inline-block;
                    font-size:{size:.1f}px;
                    font-weight:{weight:.0f};
                    opacity:{opacity:.2f};
                    margin:0.28rem 0.42rem;
                    padding:0.12rem 0.18rem;
                    line-height:1.22;
                    color:#1D4ED8;
                "
            >{safe_word}</span>
            """
        )

    html = f"""
    <div style="
        background: linear-gradient(135deg, #FFFFFF 0%, #F4F8FF 100%);
        border: 1px solid #C8D8F0;
        border-radius: 1.2rem;
        padding: 1.1rem 1.2rem;
        margin: 0.8rem 0 1rem 0;
        box-shadow: 0 10px 24px rgba(37, 99, 235, 0.07);
        word-break: keep-all;
        overflow-wrap: anywhere;
    ">
        {"".join(spans)}
    </div>
    """

    # 关键：用 st.html 渲染 HTML，不要用 st.markdown，否则某些情况下会直接显示源码
    if hasattr(st, "html"):
        st.html(html)
    else:
        import streamlit.components.v1 as components
        components.html(html, height=520, scrolling=True)



def render_wordcloud_page():
    st.header("词云")
    st.caption("从组会问题、回复和汇报主题里提取高频词。词越大，出现越多。")

    meetings = load_meetings()

    if meetings.empty:
        st.info("暂无组会。")
        return

    meetings = meetings.copy()
    meetings["month"] = meetings["meeting_date"].apply(month_label_from_date)

    available_months = sorted(
        [x for x in meetings["month"].dropna().unique().tolist() if x],
        reverse=True,
    )

    if not available_months:
        st.info("暂无可分析月份。")
        return

    c1, c2, c3 = st.columns([1.4, 2.2, 1.1])

    with c1:
        use_all_months = st.checkbox("全部月份", value=False, key="wordcloud_all_months")

    with c2:
        if use_all_months:
            selected_months = available_months
            st.caption("当前：全部月份")
        else:
            selected_months = st.multiselect(
                "选择月份",
                available_months,
                default=[available_months[0]],
                key="wordcloud_months",
            )

    with c3:
        max_words = st.slider("词数", min_value=30, max_value=150, value=80, step=10)

    if not selected_months:
        st.warning("至少选择一个月份。")
        return

    selected_meetings = meetings[meetings["month"].isin(selected_months)].copy()
    meeting_ids = selected_meetings["id"].astype(int).tolist()

    if not meeting_ids:
        st.info("所选月份没有组会。")
        return

    source = st.radio(
        "词云来源",
        ["问题文本", "回复文本", "问题 + 回复", "汇报主题", "全部文本"],
        horizontal=True,
        key="wordcloud_source",
    )

    all_questions = load_questions(None)
    questions = all_questions[all_questions["meeting_id"].isin(meeting_ids)].copy()

    talks = collect_talks_for_meetings(meeting_ids)

    texts = []

    if source in ["问题文本", "问题 + 回复", "全部文本"]:
        if not questions.empty:
            texts.extend(questions["question_text"].apply(clean_text).tolist())

    if source in ["回复文本", "问题 + 回复", "全部文本"]:
        if not questions.empty and "answer_text" in questions.columns:
            texts.extend(questions["answer_text"].apply(clean_text).tolist())

    if source in ["汇报主题", "全部文本"]:
        if not talks.empty:
            texts.extend(talks["talk_title"].apply(clean_text).tolist())

    tokens = []

    for item in texts:
        tokens.extend(tokenize_for_wordcloud(item))

    counter = Counter(tokens)

    st.subheader("组会词云")
    render_html_wordcloud(counter, max_words=max_words)

    st.subheader("高频词表")

    if counter:
        top_df = pd.DataFrame(
            counter.most_common(max_words),
            columns=["词", "出现次数"],
        )
        st.dataframe(top_df, use_container_width=True, hide_index=True)
    else:
        st.info("暂无高频词。")



user_name = render_login()

tab_live, tab_calendar, tab_stats, tab_wordcloud, tab_poll, tab_admin = st.tabs(
    ["组会现场", "组会日历", "统计评选", "词云", "匿名投票", "管理员"]
)

with tab_live:
    render_live_page(user_name)

with tab_calendar:
    render_calendar_page()

with tab_stats:
    render_stats_page()

with tab_wordcloud:
    render_wordcloud_page()

with tab_poll:
    render_poll_page(user_name)

with tab_admin:
    render_admin_page()
