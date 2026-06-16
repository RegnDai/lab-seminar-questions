import calendar
import hmac
from datetime import datetime
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
        return pd.DataFrame(columns=["id", "question_id", "voter_name", "created_at"])

    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")

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


def vote_question(question_id: int, voter_name: str) -> bool:
    try:
        supabase.table("seminar_question_votes").insert(
            {
                "question_id": int(question_id),
                "voter_name": voter_name,
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


def render_question(question, vote_count: int, has_voted: bool, user_name: str):
    question_id = int(question["id"])

    asker = clean_text(question.get("asker_name"))
    context = clean_text(question.get("context_label"))
    tag = clean_text(question.get("question_tag"))
    question_text = clean_text(question.get("question_text"))
    answer_text = clean_text(question.get("answer_text"))
    answer_by = clean_text(question.get("answer_by"))

    flags = []

    if context:
        flags.append(context)

    if tag:
        flags.append(tag)

    if bool(question.get("is_featured")):
        flags.append("精选")

    flag_text = " · ".join(flags)

    st.markdown(f"**{asker}**：{question_text}")

    if flag_text:
        st.caption(flag_text)

    if answer_text:
        st.markdown(f"> **{answer_by or '回复'}：** {answer_text}")

    c1, c2, c3 = st.columns([1, 1, 5])

    with c1:
        if st.button(
            f"👍 {vote_count}",
            key=f"vote_{question_id}_{user_name}",
            disabled=has_voted,
        ):
            ok = vote_question(question_id, user_name)
            if not ok:
                st.info("你已经点过赞了。")
            st.rerun()

    with c2:
        featured_label = "取消精选" if bool(question.get("is_featured")) else "精选"
        if st.button(featured_label, key=f"featured_{question_id}"):
            update_question_flags(
                question_id,
                is_featured=not bool(question.get("is_featured")),
            )
            st.rerun()

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

    vote_counts = (
        votes.groupby("question_id")["id"].count().to_dict()
        if not votes.empty
        else {}
    )

    user_voted = set(
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
        render_question(
            question=question,
            vote_count=int(vote_counts.get(qid, 0)),
            has_voted=qid in user_voted,
            user_name=user_name,
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

    vote_counts = (
        votes.groupby("question_id")["id"].count().reset_index(name="获赞数")
        if not votes.empty
        else pd.DataFrame(columns=["question_id", "获赞数"])
    )

    q = questions.merge(
        vote_counts,
        left_on="id",
        right_on="question_id",
        how="left",
    ).fillna({"获赞数": 0})

    q["获赞数"] = q["获赞数"].astype(int)

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric("统计月份", len(selected_months))

    with c2:
        st.metric("组会数", len(selected_meetings))

    with c3:
        st.metric("问题数", len(q))

    with c4:
        st.metric("总点赞", int(q["获赞数"].sum()))

    st.caption("当前统计范围：" + "、".join(selected_months))

    st.subheader("提问榜")

    leaderboard = (
        q.groupby("asker_name", as_index=False)
        .agg(
            提问数=("id", "count"),
            获赞数=("获赞数", "sum"),
            精选问题数=("is_featured", "sum"),
        )
        .rename(columns={"asker_name": "姓名"})
        .sort_values(["精选问题数", "获赞数", "提问数"], ascending=False)
    )

    st.dataframe(leaderboard, use_container_width=True, hide_index=True)

    st.subheader("按月份统计")

    q_with_meeting = q.merge(
        meetings[["id", "meeting_date", "month", "title"]],
        left_on="meeting_id",
        right_on="id",
        how="left",
        suffixes=("", "_meeting"),
    )

    by_month = (
        q_with_meeting.groupby("month", as_index=False)
        .agg(
            问题数=("id", "count"),
            提问人数=("asker_name", "nunique"),
            获赞数=("获赞数", "sum"),
            精选问题数=("is_featured", "sum"),
        )
        .rename(columns={"month": "月份"})
        .sort_values("月份", ascending=False)
    )

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

    high = q.merge(
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

    high = high.sort_values(["is_featured", "获赞数", "created_at"], ascending=[False, False, True]).copy()

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
                "获赞数": int(row.get("获赞数", 0)),
                "精选": "是" if bool(row.get("is_featured")) else "",
            }
        )

    st.subheader("问题列表")
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

                featured_input = st.checkbox(
                    "精选问题",
                    value=bool(question.get("is_featured")),
                    key=f"admin_featured_{question_id}",
                )

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


user_name = render_login()

tab_live, tab_calendar, tab_stats, tab_admin = st.tabs(
    ["组会现场", "组会日历", "统计评选", "管理员"]
)

with tab_live:
    render_live_page(user_name)

with tab_calendar:
    render_calendar_page()

with tab_stats:
    render_stats_page()

with tab_admin:
    render_admin_page()
