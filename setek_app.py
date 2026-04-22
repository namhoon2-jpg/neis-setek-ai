import streamlit as st
import pdfplumber
import google.generativeai as genai
import pandas as pd
import numpy as np
import io
import requests
from datetime import datetime
from duckduckgo_search import DDGS

# ==========================================
# 0. 설정 (비밀번호 및 양방향 시트 연결)
# ==========================================
APP_PASSWORD = "2848" 

GSHEET_CSV_URL = st.secrets.get("GSHEET_CSV_URL", "")
GSHEET_WEBAPP_URL = st.secrets.get("GSHEET_WEBAPP_URL", "")

st.set_page_config(page_title="NEIS 세특 AI 어시스턴트", layout="wide")

# ==========================================
# 1. 로그인 로직
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 교과세특 AI 어시스턴트 로그인")
    pwd_input = st.text_input("비밀번호", type="password")
    if st.button("입장하기", type="primary"):
        if pwd_input == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("⚠️ 비밀번호가 틀렸습니다.")
    st.stop()

# ==========================================
# 2. AI 설정 및 세션 초기화
# ==========================================
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.5-flash")
    embed_model = "models/text-embedding-004" 
except Exception as e:
    st.error(f"⚠️ API 설정 오류: {e}")

if "db_texts" not in st.session_state: st.session_state.db_texts = []
if "db_embeddings" not in st.session_state: st.session_state.db_embeddings = []
if "current_result" not in st.session_state: st.session_state.current_result = ""
if "current_template" not in st.session_state: st.session_state.current_template = ""
if "target_bytes" not in st.session_state: st.session_state.target_bytes = 1500

def get_byte_length(text): return len(text.encode('utf-8'))

# ==========================================
# 3. 구글 시트 동기화 (읽기)
# ==========================================
def sync_with_gsheet():
    if not GSHEET_CSV_URL: return 0
    try:
        response = requests.get(GSHEET_CSV_URL)
        df = pd.read_csv(io.StringIO(response.text))
        texts = df.iloc[:, 0].dropna().astype(str).tolist()
        if texts:
            result = genai.embed_content(model=embed_model, content=texts)
            st.session_state.db_texts = texts
            st.session_state.db_embeddings = result['embedding']
        return len(texts)
    except Exception: return 0

# ==========================================
# 4. 화면 구성 및 지식 영구 누적 (쓰기)
# ==========================================
st.title("📝 NEIS 세특 AI 어시스턴트")

with st.sidebar:
    st.header("🧠 AI 지식 저장소")
    
    db_file = st.file_uploader("새로운 가이드라인/우수사례 추가 (.xlsx)")
    if db_file and st.button("💾 구글 시트에 영구 누적하기", use_container_width=True):
        with st.spinner("데이터를 전송 중입니다..."):
            df = pd.read_excel(db_file)
            new_texts = df.iloc[:, 0].dropna().astype(str).tolist()
            if GSHEET_WEBAPP_URL:
                try:
                    response = requests.post(GSHEET_WEBAPP_URL, json={"texts": new_texts})
                    if response.status_code == 200:
                        st.success(f"✅ {len(new_texts)}개의 지식 저장 완료!")
                        sync_with_gsheet()
                except Exception as e: st.error(f"에러: {e}")
            else: st.error("GSHEET_WEBAPP_URL 누락")
    st.divider()
    
    st.caption("현재 기억 상태")
    if st.button("🔄 최신 지식 불러오기", use_container_width=True):
        count = sync_with_gsheet()
        st.success(f"현재 총 {count}개의 지식 탑재.")

    st.divider()
    st.header("📏 세특 설정")
    target_bytes = st.slider("목표 절대 최대치 (Bytes)", min_value=500, max_value=1500, value=1500, step=100)
    st.session_state.target_bytes = target_bytes
    
    st.divider()
    subject = st.text_input("과목명", placeholder="예: 미적분, 문학")
    grade_level = st.text_input("성취도/등급", placeholder="예: A")
    teacher_eval = st.text_area("교사 관찰 팩트 (키워드)", placeholder="예: 발표에서 오개념 수정함. 조장 역할 수행.", height=100)
    pdf_file = st.file_uploader("학생 보고서 (PDF) - 선택", type=["pdf"])

if st.session_state.authenticated and not st.session_state.db_texts and GSHEET_CSV_URL:
    sync_with_gsheet()

# ==========================================
# 5. 생성 엔진
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    if not subject or not teacher_eval:
        st.warning("👈 과목명과 관찰 팩트를 입력해주세요.")
    else:
        with st.spinner("1/4: 학생 데이터를 분석 중입니다..."):
            pdf_text = "제출된 추가 보고서 없음"
            if pdf_file:
                with pdfplumber.open(pdf_file) as pdf:
                    pdf_text = "".join([pg.extract_text() for pg in pdf.pages if pg.extract_text()])
            
        with st.spinner("2/4: 최신 동향 검색 중..."):
            kw_p = f"다음 내용에서 핵심 트렌드 검색어 1개만 출력: {teacher_eval} {pdf_text[:500]}"
            kw = model.generate_content(kw_p).text.strip()
            try:
                results = DDGS().text(f"{kw} 최신 연구 동향", max_results=1)
                trend = results[0]['body'] if results else "정보 없음"
            except: trend = "검색 생략"

        with st.spinner("3/4: 뼈대 설계 중..."):
            guidelines = "\n".join(st.session_state.db_texts) if st.session_state.db_texts else "객관적이고 건조한 문체."
            safe_chars = (st.session_state.target_bytes - 100) // 3 # 안전한 글자수 여유분 계산
            
            bp_prompt = f"""
            당신은 최고의 고등학교 {subject} 교사입니다.
            아래 [공통 가이드라인]을 지켜서 '{subject}' 과목의 세특 우수 사례 1개를 가상으로 작성하세요.
            
            [신뢰성 구조]
            "학생의 실제 활동(팩트)" + "교사의 객관적이고 짧은 평가" 패턴으로만 구성하세요.
            
            [공통 가이드라인]
            {guidelines}
            """
            best_practice_template = model.generate_content(bp_prompt).text.strip()
            st.session_state.current_template = best_practice_template

        with st.spinner("4/4: 제한된 팩트 내에서 최종 세특 작성 중..."):
            prompt = f"""
            아래 [데이터]만을 활용하여 학생의 실제 NEIS 교과세특을 작성하세요.

            [데이터]
            - 과목명: {subject}
            - 성취도: {grade_level}
            - 교사 관찰 팩트: {teacher_eval}
            - 학생 보고서: {pdf_text[:2000]}
            - 융합 트렌드: {trend}

            [절대 모방 템플릿 (문장 구조만 모방할 것)]
            {best_practice_template}

            [🔥 3대 절대 엄수 규칙 🔥]
            1. 오직 팩트 한정: [데이터]에 명시된 활동, 개념, 도서명, 역량 외에는 단 하나도 지어내거나 덧붙이지 마세요. 보고서가 없다면 관찰 팩트만으로만 작성하세요. 
            2. 분량 절대 사수: 나이스 입력 최대치가 {st.session_state.target_bytes}바이트입니다. 초과를 막기 위해 반드시 한글 {safe_chars}자(약 {st.session_state.target_bytes - 100}바이트) 이내로 짧고 밀도 있게 마무리하세요.
            3. 태그 금지: 결과물 맨 앞이나 뒤에 `[{subject}]`, `제목:`, `본문:` 같은 어떠한 태그도 적지 마세요. 오직 단일 문단으로 된 내용만 바로 출력하세요.
            """
            response = model.generate_content(prompt)
            st.session_state.current_result = response.text.strip().replace('\n', ' ')

# ==========================================
# 6. 결과 출력
# ==========================================
if st.session_state.current_result:
    res_text = st.session_state.current_result
    # 만약 AI가 실수로 [과목명]을 넣었다면 파이썬 단에서 한 번 더 강제 삭제 처리
    tag_to_remove = f"[{subject}]"
    if res_text.startswith(tag_to_remove):
        res_text = res_text[len(tag_to_remove):].strip()

    st.divider()
    st.subheader("🎯 생성된 맞춤형 세특 (팩트 한정 & 분량 제한)")
    byte_len = get_byte_length(res_text)
    target = st.session_state.target_bytes
    
    if byte_len > target:
        st.error(f"⚠️ 목표 제한 초과: {byte_len} / {target} Bytes (직접 일부 삭제가 필요합니다)")
    else:
        st.success(f"✅ 안전 분량 달성: {byte_len} / {target} Bytes")
    
    final_text = st.text_area("결과 확인/수정", value=res_text, height=200)

    with st.expander("🔍 AI가 설계한 '활동+평가 구조' 뼈대 훔쳐보기"):
        st.info(st.session_state.current_template)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame([{
            "날짜": datetime.now().strftime('%Y-%m-%d %H:%M'), 
            "과목": subject, 
            "등급": grade_level, 
            "관찰팩트": teacher_eval, 
            "생성세특": final_text
        }]).to_excel(writer, index=False)
        
    st.download_button(
        label="📂 작성된 세특 엑셀로 다운로드 (개인 PC 보관)",
        data=output.getvalue(),
        file_name=f"{subject}_세특기록_{datetime.now().strftime('%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
