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
    
    db_file = st.file_uploader("새로운 가이드라인/우수사례 추가 (.xlsx)", help="여기에 올린 데이터는 구글 시트에 영구적으로 누적 저장됩니다.")
    if db_file and st.button("💾 구글 시트에 영구 누적하기", use_container_width=True):
        with st.spinner("데이터를 구글 시트로 전송 중입니다..."):
            df = pd.read_excel(db_file)
            new_texts = df.iloc[:, 0].dropna().astype(str).tolist()
            
            if GSHEET_WEBAPP_URL:
                try:
                    response = requests.post(GSHEET_WEBAPP_URL, json={"texts": new_texts})
                    if response.status_code == 200:
                        st.success(f"✅ {len(new_texts)}개의 지식이 구글 시트에 영구 저장되었습니다!")
                        sync_with_gsheet()
                    else:
                        st.error("구글 시트 전송 중 오류가 발생했습니다.")
                except Exception as e:
                    st.error(f"통신 에러: {e}")
            else:
                st.error("Secrets에 GSHEET_WEBAPP_URL이 설정되지 않았습니다.")

    st.divider()
    
    st.caption("현재 기억 상태")
    if st.button("🔄 최신 지식 불러오기", use_container_width=True):
        count = sync_with_gsheet()
        st.success(f"현재 총 {count}개의 지식이 뇌에 탑재되었습니다.")

    st.divider()
    
    subject = st.text_input("과목명", placeholder="예: 미적분, 문학, 동아시아사")
    grade_level = st.text_input("성취도/등급", placeholder="예: A (또는 2등급)")
    teacher_eval = st.text_area("교사 관찰 팩트 (키워드)", height=100)
    
    # 💡 수정된 부분: (선택) 표시 추가
    pdf_file = st.file_uploader("학생 보고서 (PDF) - 선택", type=["pdf"])

# 첫 구동 시 가이드라인 자동 로드
if st.session_state.authenticated and not st.session_state.db_texts and GSHEET_CSV_URL:
    sync_with_gsheet()

# ==========================================
# 5. 생성 엔진
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    # 💡 수정된 부분: pdf_file이 없어도 경고를 띄우지 않고 넘어갑니다.
    if not subject or not teacher_eval:
        st.warning("👈 과목명과 관찰 팩트를 입력해주세요. (보고서는 선택사항입니다)")
    else:
        with st.spinner("1/4: 학생 데이터를 분석 중입니다..."):
            # 💡 수정된 부분: PDF가 있으면 읽고, 없으면 없다고 기록합니다.
            pdf_text = "제출된 추가 보고서 없음"
            if pdf_file:
                with pdfplumber.open(pdf_file) as pdf:
                    pdf_text = "".join([pg.extract_text() for pg in pdf.pages if pg.extract_text()])
            
        with st.spinner("2/4: 최신 기술/학술 동향을 웹에서 검색 중입니다..."):
            # PDF가 없으면 교사 관찰 팩트에서만 핵심 키워드를 뽑습니다.
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
            아래 [공통 가이드라인 및 누적 지식]을 완벽하게 지켜서, '{teacher_eval}' 내용과 유사한 방향성을 가진 
            {subject} 과목의 '가장 이상적인 세특 우수 사례' 1개를 400자 내외로 가상으로 지어내세요.
            
            [공통 가이드라인 및 누적 지식]
            {guidelines}
            """
            best_practice_template = model.generate_content(bp_prompt).text.strip()
            st.session_state.current_template = best_practice_template

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
            {best_practice_template}

            [최종 작성 원칙]
            1. 분량: 한글 기준 400자 ~ 450자 사이 (하나의 문단).
            2. 어투: AI 특유의 주관적 찬양 절대 금지.
            3. 마크다운 기호 절대 금지.
            """
            response = model.generate_content(prompt)
            st.session_state.current_result = response.text.strip().replace('\n', ' ')

# ==========================================
# 6. 결과 출력
# ==========================================
if st.session_state.current_result:
    res_text = st.session_state.current_result
    st.divider()
    st.subheader("🎯 생성된 맞춤형 세특")
    byte_len = get_byte_length(res_text)
    
    if byte_len <= 1500: st.success(f"✅ NEIS 바이트 통과: {byte_len}/1500")
    else: st.error(f"⚠️ 바이트 초과: {byte_len}/1500")
    
    final_text = st.text_area("결과 확인/수정", value=res_text, height=200)

    with st.expander("🔍 AI가 먼저 설계한 '가상의 최우수 사례 뼈대' 훔쳐보기"):
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
