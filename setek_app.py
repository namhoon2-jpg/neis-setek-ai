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
# 0. 설정 (비밀번호 및 시트 연결)
# ==========================================
APP_PASSWORD = "2848" 

# 구글 시트 URL (공통 가이드라인만 적힌 시트)
GSHEET_CSV_URL = st.secrets.get("GSHEET_KNOWLEDGE_URL", "")

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
if "current_template" not in st.session_state: st.session_state.current_template = "" # 💡 템플릿 저장소 추가

def get_byte_length(text):
    return len(text.encode('utf-8'))

# ==========================================
# 3. 구글 시트 동기화 (공통 가이드라인 전용)
# ==========================================
def sync_with_gsheet():
    if not GSHEET_CSV_URL: return 0
    try:
        response = requests.get(GSHEET_CSV_URL)
        df = pd.read_csv(io.StringIO(response.text))
        texts = df.iloc[:, 0].dropna().astype(str).tolist()
        result = genai.embed_content(model=embed_model, content=texts)
        st.session_state.db_texts = texts
        st.session_state.db_embeddings = result['embedding']
        return len(texts)
    except Exception: return 0

# ==========================================
# 4. 화면 구성
# ==========================================
st.title("📝 NEIS 세특 AI 어시스턴트 (V7.1)")

with st.sidebar:
    st.header("🔄 공통 가이드라인 동기화")
    if st.button("🌐 구글 시트 가이드라인 불러오기", use_container_width=True):
        count = sync_with_gsheet()
        if count > 0: st.success(f"✅ {count}개의 작성 규칙을 뇌에 새겼습니다!")

    st.divider()
    subject = st.selectbox("과목명 선택", ["미적분", "확률과 통계", "기하", "문학", "동아시아사", "물리학Ⅰ", "기타(직접입력)"])
    if subject == "기타(직접입력)":
        subject = st.text_input("과목명을 입력하세요")
        
    grade_level = st.text_input("성취도", placeholder="예: A")
    teacher_eval = st.text_area("관찰 팩트", height=100)
    pdf_file = st.file_uploader("보고서(PDF)", type=["pdf"])

# 첫 구동 시 가이드라인 자동 로드
if st.session_state.authenticated and not st.session_state.db_texts and GSHEET_CSV_URL:
    sync_with_gsheet()

# ==========================================
# 5. 생성 엔진 (4단계 Chain-of-Thought)
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    if not subject or not teacher_eval or not pdf_file:
        st.warning("👈 과목명, 팩트, 보고서를 모두 입력해주세요.")
    else:
        with st.spinner("1/4: 학생 보고서를 분석 중입니다..."):
            pdf_text = ""
            with pdfplumber.open(pdf_file) as pdf:
                pdf_text = "".join([pg.extract_text() for pg in pdf.pages if pg.extract_text()])
            
        with st.spinner("2/4: 최신 기술/학술 동향을 웹에서 검색 중입니다..."):
            kw_p = f"다음 내용에서 핵심 트렌드 검색어 1개만 출력: {teacher_eval} {pdf_text[:500]}"
            kw = model.generate_content(kw_p).text.strip()
            try:
                results = DDGS().text(f"{kw} 최신 연구 동향", max_results=1)
                trend = results[0]['body'] if results else "정보 없음"
            except: trend = "검색 지연"

        with st.spinner(f"3/4: AI가 '{subject}' 과목의 최우수 사례 뼈대를 자체 설계 중입니다..."):
            guidelines = "\n".join(st.session_state.db_texts) if st.session_state.db_texts else "객관적이고 건조한 문체로 작성할 것."
            
            bp_prompt = f"""
            당신은 최고의 고등학교 {subject} 교사입니다.
            아래 [공통 가이드라인]을 완벽하게 지켜서, '{teacher_eval}' 내용과 유사한 방향성을 가진 
            {subject} 과목의 '가장 이상적인 세특 우수 사례' 1개를 400자 내외로 가상으로 지어내세요.
            이 예시는 다음 단계에서 문체와 구조의 템플릿으로 쓰입니다.
            
            [공통 가이드라인]
            {guidelines}
            """
            best_practice_template = model.generate_content(bp_prompt).text.strip()
            st.session_state.current_template = best_practice_template # 💡 생성된 템플릿을 메모리에 저장

        with st.spinner("4/4: 학생의 팩트를 템플릿에 융합하여 최종 세특을 작성합니다..."):
            prompt = f"""
            아래 제공된 [데이터]를 활용하여 학생의 실제 NEIS 교과세특을 작성하세요.

            [데이터]
            - 과목명: {subject}
            - 성취도/등급: {grade_level}
            - 실제 교사 관찰 팩트: {teacher_eval}
            - 학생 제출 보고서 내용: {pdf_text[:2000]}
            - 융합할 최신 트렌드: {trend}

            [절대 모방해야 할 최우수 사례 템플릿]
            아래는 AI가 설계한 완벽한 템플릿입니다. 이 템플릿의 **문장 구조, 어투(~함, ~임), 전문성 깊이**를 철저하게 모방하되, 
            내용은 반드시 [데이터]에 있는 이 학생의 실제 팩트만 반영하세요.
            {best_practice_template}

            [최종 작성 원칙]
            1. 분량: 한글 기준 400자 ~ 450자 사이 (하나의 문단).
            2. 어투: '놀라운', '탁월한' 등 AI 특유의 주관적 찬양 절대 금지.
            3. 마크다운(볼드체 등) 기호 절대 금지.
            """
            response = model.generate_content(prompt)
            st.session_state.current_result = response.text.strip().replace('\n', ' ')

# ==========================================
# 6. 결과 출력 및 다운로드
# ==========================================
if st.session_state.current_result:
    res_text = st.session_state.current_result
    st.divider()
    st.subheader("🎯 생성된 맞춤형 세특")
    byte_len = get_byte_length(res_text)
    
    if byte_len <= 1500: st.success(f"✅ NEIS 바이트 통과: {byte_len}/1500")
    else: st.error(f"⚠️ 바이트 초과: {byte_len}/1500")
    
    final_text = st.text_area("결과 확인/수정", value=res_text, height=200)

    # 💡 AI가 설계한 템플릿을 볼 수 있는 토글(Expander) 추가
    with st.expander("🔍 AI가 먼저 설계한 '가상의 최우수 사례 뼈대' 훔쳐보기"):
        st.markdown("**안내:** AI가 선생님의 구글 시트 가이드라인을 바탕으로 제일 먼저 지어낸 '이상적인 모범 답안'입니다. 최종 세특은 이 글의 말투와 전개 방식을 철저히 베껴서 작성되었습니다.")
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
