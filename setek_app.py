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
    db_file = st.file_uploader("지식 추가 (Excel 또는 PDF)", type=["xlsx", "pdf"])
    
    if db_file and st.button("💾 구글 시트에 영구 누적하기", use_container_width=True):
        with st.spinner("지식을 추출하여 동기화 중입니다..."):
            new_texts = []
            if db_file.name.endswith('.xlsx'):
                df = pd.read_excel(db_file)
                new_texts = df.iloc[:, 0].dropna().astype(str).tolist()
            elif db_file.name.endswith('.pdf'):
                with pdfplumber.open(db_file) as pdf:
                    full_pdf_text = "".join([pg.extract_text() for pg in pdf.pages if pg.extract_text()])
                    new_texts = [full_pdf_text]
            
            if new_texts and GSHEET_WEBAPP_URL:
                try:
                    response = requests.post(GSHEET_WEBAPP_URL, json={"texts": new_texts})
                    if response.status_code == 200:
                        st.success(f"✅ {len(new_texts)}건 지식 저장 완료!")
                        sync_with_gsheet()
                except Exception as e: st.error(f"에러: {e}")

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
    subject = st.text_input("과목명", placeholder="예: 미적분")
    grade_level = st.text_input("성취도/등급", placeholder="예: A")
    
    teacher_eval = st.text_area("교사 관찰 팩트 (상세 입력 권장)", placeholder="학생의 활동 계기, 구체적인 활동 과정, 결과, 그리고 교사로서 엿본 역량을 자세히 적어주세요.", height=250)
    
    pdf_file = st.file_uploader("학생 보고서 (PDF) - 선택", type=["pdf"], accept_multiple_files=True)

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
            student_report_text = "제출된 추가 보고서 없음"
            if pdf_file:
                student_report_text = ""
                for file in pdf_file:
                    with pdfplumber.open(file) as pdf:
                        student_report_text += "".join([pg.extract_text() for pg in pdf.pages if pg.extract_text()]) + "\n"
            
        with st.spinner("2/4: 최신 동향 검색 중..."):
            kw_p = f"다음 내용에서 핵심 트렌드 검색어 1개만 출력: {teacher_eval} {student_report_text[:500]}"
            kw = model.generate_content(kw_p).text.strip()
            try:
                results = DDGS().text(f"{kw} 최신 연구 동향", max_results=1)
                trend = results[0]['body'] if results else "정보 없음"
            except: trend = "검색 생략"

        with st.spinner("3/4: 입체적 단일 문단 뼈대 설계 중..."):
            guidelines = "\n".join(st.session_state.db_texts) if st.session_state.db_texts else "객관적이고 건조한 문체."
            
            # 💡 V18 핵심 1: 뼈대부터 관찰 동사 및 메타 단어 금지 세팅
            bp_prompt = f"""
            당신은 최고의 고등학교 {subject} 교사입니다.
            [입체적 서사 구조] 반드시 (계기 -> 과정 -> 결과 -> 교사 평가)의 순서를 엄수하되, 문장 간의 원인과 결과가 매끄럽게 이어지는 논리적 문맥을 형성하세요. 단순 문장 나열이나 번호 매기기는 절대 금지합니다.
            [관찰 가능한 행동 동사] '이해함', '깨달음', '느낌' 같은 학생의 내면적 상태를 지레짐작하는 동사를 금지합니다. 대신 '설명함', '적용함', '증명함', '구현함', '도출함' 등 교사가 눈으로 관찰 가능한 능동적 행동 동사만 사용하세요.
            [주어 및 금지어] '학생은' 등 주어를 쓰지 말고, 본문에 '세특', '교과세특', '생기부' 같은 메타 단어도 절대 쓰지 마세요.
            [공통 가이드라인] {guidelines}
            위 규칙을 지켜 '{subject}' 과목의 세특 뼈대를 가상으로 작성하세요.
            """
            best_practice_template = model.generate_content(bp_prompt).text.strip()
            st.session_state.current_template = best_practice_template

        with st.spinner("4/4: 최종 세특 작성 중..."):
            max_b = st.session_state.target_bytes
            min_b = int(max_b * 0.8)
            max_c = (max_b // 3) - 15  
            min_c = (min_b // 3)
            
            prompt = f"""
            아래 [데이터]만을 활용하여 학생의 실제 NEIS 교과세특을 작성하세요.

            [데이터]
            - 과목명: {subject}
            - 성취도: {grade_level}
            - 교사 관찰 팩트: {teacher_eval}
            - 학생 보고서: {student_report_text[:2000]}
            - 융합 트렌드: {trend}

            [절대 모방 템플릿] 
            {best_practice_template}

            [🔥 9대 절대 엄수 규칙 🔥]
            1. NEIS 호환 (수식/기호 금지): 나이스 시스템 오류 방지를 위해 모든 특수기호, 첨자, LaTeX 수식을 한글로 풀어서 설명하세요.
            2. 분량 폭주 절대 금지: 나이스 제한치({max_b}바이트)를 고려하여 한글 기준 절대 {max_c}자를 넘지 않도록 문장을 압축하세요. (목표: {min_c}자 ~ {max_c}자).
            3. 하나의 통글(단일 문단): 번호(1, 2, 3...), 소제목, 줄바꿈, 마크다운 기호를 모두 없애고 완벽한 하나의 문단으로 묶으세요.
            4. 주어 완벽 생략: '학생은', '본 학생은', '자신은' 등 불필요한 주
