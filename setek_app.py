import streamlit as st
import pdfplumber
import google.generativeai as genai
import pandas as pd
import numpy as np
import io
import requests
from datetime import datetime

# DuckDuckGo 라이브러리 로드 (안전 처리)
try:
    from duckduckgo_search import DDGS
    ddgs_available = True
except ImportError:
    ddgs_available = False

# ==========================================
# 0. 안전한 Secrets 호출 함수 
# ==========================================
def get_secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return default

APP_PASSWORD = "2848" 
GSHEET_CSV_URL = get_secret("GSHEET_CSV_URL", "")
GSHEET_WEBAPP_URL = get_secret("GSHEET_WEBAPP_URL", "")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY", "")

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
if not GEMINI_API_KEY:
    st.error("⚠️ Secrets 설정 오류: GEMINI_API_KEY가 입력되지 않았습니다.")
    st.stop()

try:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")
    embed_model = "models/text-embedding-004" 
except Exception as e:
    st.error(f"⚠️ 구글 AI 초기화 오류: {e}")
    st.stop()

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
        
        if not df.empty and len(df.columns) > 0:
            texts = df.iloc[:, 0].dropna().astype(str).tolist()
            if texts:
                texts = texts[:100] 
                result = genai.embed_content(model=embed_model, content=texts)
                st.session_state.db_texts = texts
                st.session_state.db_embeddings = result['embedding']
                return len(texts)
        return 0
    except Exception as e:
        st.sidebar.warning(f"시트 동기화 실패: {e}")
        return 0

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
            try:
                if db_file.name.endswith('.xlsx'):
                    df = pd.read_excel(db_file)
                    if not df.empty and len(df.columns) > 0:
                        new_texts = df.iloc[:, 0].dropna().astype(str).tolist()
                elif db_file.name.endswith('.pdf'):
                    with pdfplumber.open(db_file) as pdf:
                        extracted = [pg.extract_text() for pg in pdf.pages if pg.extract_text()]
                        full_pdf_text = "".join(extracted)
                        if full_pdf_text.strip():
                            new_texts = [full_pdf_text]
                
                if new_texts and GSHEET_WEBAPP_URL:
                    response = requests.post(GSHEET_WEBAPP_URL, json={"texts": new_texts})
                    if response.status_code == 200:
                        st.success(f"✅ {len(new_texts)}건 지식 저장 완료!")
                        sync_with_gsheet()
                else:
                    st.warning("추출할 텍스트가 없거나 URL 설정이 누락되었습니다.")
            except Exception as e:
                st.error(f"파일 처리 에러: {e}")

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

st.subheader("👨‍🏫 교사 관찰 및 평가 (키워드 위주 작성)")
col1, col2 = st.columns(2)

with col1:
    report_eval = st.text_area(
        "📄 활동/탐구 역량 팩트", 
        placeholder="어떤 계기로 무엇을 탐구했고 어떤 결과를 냈는지 학생의 구체적인 '행동과 팩트'를 적어주세요.", 
        height=180
    )

with col2:
    general_eval = st.text_area(
        "🧑‍🏫 교사의 최종 평가 (인성/태도)", 
        placeholder="이 활동을 지켜본 교사로서 학생의 인성, 태도, 성장 가능성에 대한 평가를 적어주세요.", 
        height=180
    )

pdf_files = st.file_uploader("학생 보고서 (PDF) - 선택", type=["pdf"], accept_multiple_files=True)

if st.session_state.authenticated and not st.session_state.db_texts and GSHEET_CSV_URL:
    sync_with_gsheet()

# ==========================================
# 5. 생성 엔진
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    if not subject or (not report_eval and not general_eval):
        st.warning("👈 과목명과 최소 하나 이상의 평가(보고서 관련 또는 종합 평가)를 입력해주세요.")
    else:
        with st.spinner("1/4: 학생 데이터를 분석 중입니다..."):
            student_report_text = ""
            if pdf_files:
                for file in pdf_files:
                    try:
                        with pdfplumber.open(file) as pdf:
                            for pg in pdf.pages:
                                text = pg.extract_text()
                                if text: student_report_text += text + "\n"
                    except Exception as e:
                        st.warning(f"{file.name} 추출 오류: {e}")
            
            has_report = bool(student_report_text.strip())
            if not has_report:
                student_report_text = "제출된 추가 보고서 없음"
            
        with st.spinner("2/4: 최신 동향 검색 중..."):
            trend = "검색 생략"
            if ddgs_available and has_report:
                try:
                    kw_p = f"다음 내용에서 핵심 검색어 1개만 출력: {report_eval} {student_report_text[:500]}"
                    kw_resp = model.generate_content(kw_p)
                    if kw_resp.parts:
                        kw = kw_resp.text.strip()
                        results = list(DDGS().text(f"{kw} 최신 동향", max_results=1))
                        if results: trend = results[0].get('body', '정보 없음')
                except Exception: pass

        with st.spinner("3/4: 입체적 단일 문단 뼈대 설계 중..."):
            guidelines = "\n".join(st.session_state.db_texts) if st.session_state.db_texts else "객관적이고 건조한 문체."
            
            bp_prompt = f"""
            당신은 최고의 고등학교 {subject} 교사입니다.
            [관찰 가능한 행동 동사] 교사가 직접 볼 수 없는 내면 상태('이해함', '체득함', '깨달음')는 절대 금지하고, 반드시 눈으로 확인 가능한 능동적 행동('증명함', '설명함', '적용함')으로 우회하여 작성하세요.
            [자연스러운 서사] 동기-과정-결과-평가가 기계적인 나열이 아닌, "A라는 호기심(동기)으로 B를 분석했고(과정), 그 결과 C를 도출함(결과). 이를 통해 D라는 역량을 확인함(평가)" 처럼 인과관계로 매끄럽게 이어지게 설계하세요.
            [공통 가이드라인] {guidelines}
            위 대전제를 지켜 '{subject}' 과목의 세특 뼈대를 가상으로 작성하세요.
            """
            best_practice_template = model.generate_content(bp_prompt).text.strip()
            st.session_state.current_template = best_practice_template

        with st.spinner("4/4: 데이터 분할 융합 및 최종 세특 작성 중..."):
            max_b = st.session_state.target_bytes
            min_b = int(max_b * 0.8)
            max_c = (max_b // 3) - 10  
            min_c = (min_b // 3)
            
            prompt = f"""
            아래 [데이터]만을 활용하여 학생의 실제 NEIS 교과세특을 작성하세요.

            [데이터]
            - 과목명: {subject}
            - 성취도: {grade_level}
            - 활동/탐구 역량 팩트: {report_eval}
            - 교사의 최종 평가 (인성/태도): {general_eval}
            - 학생 보고서 텍스트: {student_report_text[:2000]}
            - 융합 트렌드: {trend}

            [절대 모방 템플릿] 
            {best_practice_template}

            [🔥 대전제: AI 냄새 완벽 제거 & 능동적 관찰 무결성 🔥]
            1. 관찰 가능한 능동태 동사 강제 (매우 중요): 교사가 직접 확인할 수 없는 학생의 내면 상태("이해함", "체득함", "깨달음", "느낌")를 묘사하는 동사를 절대 사용하지 마세요. 대신 학생의 역량을 증명할 수 있는 구체적인 능동적 행동("~을 수학적으로 증명함", "~을 논리적으로 설명함", "~원리를 적용하여 모델링함", "~분석 결과를 도출함")으로 우회하여 서술하세요.
            2. 분량 절대 강제 (생존 규칙): 한글 글자 수를 무조건 **최소 {min_c}자 이상, 최대 {max_c}자 이하**로 꽉 채워 작성하세요. 미달 시 절대 안 됩니다.
            3. 상투적 표현 철폐: "~활동을 통해", "~과정에서", "~뿐만 아니라", "보여줌", "탁월한", "우수한" 등 식상한 전환어와 주관적 찬양을 완벽히 배제하세요. 오직 건조한 팩트로만 구성하세요.
            4. 자연스러운 4단 흐름: [활동 계기] ➡️ [구체적 탐구 과정] ➡️ [결과 도출] ➡️ [교사의 최종 평가] 순으로 이어지되, 번호나 소제목 없이 하나의 덩어리(단일 문단) 안에서 물 흐르듯 인과관계로 연결되게 작성하세요.
            5. 수식 한글화: NEIS 오류 방지를 위해 기호, 첨자, 수식을 한글 개념어(예: 삼각함수, 첫 번째 길이 등)로 풀어 쓰세요.
            6. 주어/메타 단어 금지: '학생은', '실명', '세특', '생기부' 등의 단어를 원천 차단하세요.
            7. 완벽한 음슴체: 모든 문장 끝은 명사형 종결어미(~함, ~임, ~됨 등)로 끝내고, 결과물 앞뒤에 과목명이나 태그를 달지 마세요.
            """
            response = model.generate_content(prompt)
            st.session_state.current_result = response.text.strip().replace('\n', ' ')

# ==========================================
# 6. 결과 출력
# ==========================================
if st.session_state.current_result:
    res_text = st.session_state.current_result
    
    tags_to_remove = [f"[{subject}]", f"{subject}", "세특 우수 사례:", "가상 세특:", "최종 세특:", "1. ", "동기:", "탐구 과정:"]
    for tag in tags_to_remove:
        if res_text.startswith(tag):
            res_text = res_text[len(tag):].strip()

    st.divider()
    st.subheader("🎯 생성된 맞춤형 세특 (능
