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

# 💡 V22 핵심 1: 평가 입력창 2단 분리
st.subheader("👨‍🏫 교사 관찰 및 평가 (키워드 위주 작성)")
col1, col2 = st.columns(2)

with col1:
    report_eval = st.text_area(
        "📄 보고서 관련 평가 (탐구 역량)", 
        placeholder="보고서의 완성도, 논리적 추론력, 자료 해석 능력 등 탐구 과정에서 보인 구체적인 하드 스킬을 적어주세요.\n(예: 공식 유도 과정이 치밀함, 데이터 시각화 능력이 뛰어남)", 
        height=180
    )

with col2:
    general_eval = st.text_area(
        "🧑‍🏫 그 외 종합 평가 (인성/태도)", 
        placeholder="수업 태도, 지적 호기심, 끈기, 리더십 등 소프트 스킬이나 최종 세특 마지막 줄에 들어갈 종합 평가를 적어주세요.\n(예: 포기하지 않고 질문하는 태도, 모둠원을 이끄는 리더십)", 
        height=180
    )

pdf_files = st.file_uploader("학생 보고서 (PDF) - 선택", type=["pdf"], accept_multiple_files=True)

if st.session_state.authenticated and not st.session_state.db_texts and GSHEET_CSV_URL:
    sync_with_gsheet()

# ==========================================
# 5. 생성 엔진
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    # 두 평가 칸 중 하나라도 비어있으면 작성 가능하도록 유연성 부여
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
            [입체적 서사 구조] 반드시 (계기 -> 과정 -> 결과 -> 교사 평가)의 순서를 엄수하되, 문장 간의 원인과 결과가 매끄럽게 이어지는 논리적 문맥을 형성하세요.
            [주어 및 금지어] 주어를 쓰지 말고, 본문에 '세특', '생기부' 같은 단어도 절대 쓰지 마세요.
            [공통 가이드라인] {guidelines}
            위 규칙을 지켜 '{subject}' 과목의 세특 뼈대를 가상으로 작성하세요.
            """
            best_practice_template = model.generate_content(bp_prompt).text.strip()
            st.session_state.current_template = best_practice_template

        with st.spinner("4/4: 데이터 분할 융합 및 최종 세특 작성 중..."):
            max_b = st.session_state.target_bytes
            min_b = int(max_b * 0.8)
            max_c = (max_b // 3) - 15  
            min_c = (min_b // 3)
            
            # 💡 V22 핵심 2: 두 평가 데이터의 명확한 프롬프트 매핑
            role_instruction = """
            [🔥 데이터 역할 분담 및 융합 규칙 🔥]
            1. [탐구 계기-과정-결과]: <학생 보고서>와 <보고서 관련 평가(탐구 역량)>를 융합하여 서술하세요. 보고서의 단순 요약이 아니라, 교사가 관찰한 탐구의 깊이와 논리력을 반영하여 구체적이고 능동적인 동사(적용함, 도출함 등)로 묘사하세요.
            2. [인지/인성 종합 및 최종 평가]: <그 외 종합 평가(인성/태도)>에 작성된 내용은 탐구 과정 서술 전반에 끈기, 태도 등의 부사로 자연스럽게 녹여내고, 이 내용들을 집약하여 마지막 [교사 평가] 문장의 핵심 결론으로 강력하게 작성하세요.
            """
            
            prompt = f"""
            아래 [데이터]만을 활용하여 학생의 실제 NEIS 교과세특을 작성하세요.

            [데이터]
            - 과목명: {subject}
            - 성취도: {grade_level}
            - 보고서 관련 평가 (탐구 역량): {report_eval}
            - 그 외 종합 평가 (인성/태도): {general_eval}
            - 학생 보고서 텍스트: {student_report_text[:2000]}
            - 융합 트렌드: {trend}

            [절대 모방 템플릿] 
            {best_practice_template}

            {role_instruction}

            [🔥 8대 절대 엄수 규칙 🔥]
            1. NEIS 호환 (수식/기호 금지): 모든 특수기호, 첨자, LaTeX 수식을 한글 개념어로 자연스럽게 풀어서 설명하세요.
            2. 분량 폭주 절대 금지: 나이스 제한치({max_b}바이트)를 고려하여 한글 기준 절대 {max_c}자를 넘지 않도록 문장을 압축하세요. (목표: {min_c}자 ~ {max_c}자).
            3. 하나의 통글(단일 문단): 번호, 소제목, 줄바꿈, 마크다운 기호를 모두 없애고 완벽한 하나의 문단으로 묶으세요.
            4. 주어 완벽 생략: '학생은', '본 학생은', 실명 등 불필요한 주어를 원천 차단하세요.
            5. 유기적 4단 서사 구조: [활동 계기] ➡️ [구체적 탐구 과정] ➡️ [결과 도출] ➡️ [교사 평가]의 순서가 원인과 결과로 매끄럽게 연결되게 하세요.
            6. 능동적/관찰 가능한 동사: '이해함', '깨달음' 배제. 오직 관찰 가능한 능동적 행동 동사만 사용하세요.
            7. 메타 단어 절대 금지: '세특', '교과세특', '학교생활기록부' 등의 단어 작성 절대 불가.
            8. 완벽한 음슴체 강제: 모든 문장 끝은 명사형 종결어미(~함, ~임, ~됨 등)로 끝나야 합니다. 결과물 앞뒤에 과목명이나 태그를 달지 마세요.
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
    st.subheader("🎯 생성된 맞춤형 세특 (역량 & 인성 융합 완료)")
    
    byte_len = get_byte_length(res_text)
    max_target = st.session_state.target_bytes
    min_target = int(max_target * 0.8)
    
    if byte_len > max_target: 
        st.error(f"⚠️ 분량 초과: {byte_len} / 최대 {max_target} Bytes")
    elif byte_len < min_target:
        st.warning(f"⚠️ 분량 미달: {byte_len} Bytes (목표 구간: {min_target} ~ {max_target} Bytes)")
    else: 
        st.success(f"✅ 완벽 분량 달성: {byte_len} Bytes (목표 구간: {min_target} ~ {max_target} Bytes)")
    
    final_text = st.text_area("결과 확인/수정", value=res_text, height=250)

    with st.expander("🔍 AI가 설계한 뼈대 훔쳐보기 (참고용)"):
        st.info(st.session_state.current_template)

    # 💡 V22 핵심 3: 엑셀 저장 시 두 평가 내용을 묶어서 저장
    combined_eval = f"[탐구 역량] {report_eval}\n[인성/태도] {general_eval}"
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame([{
            "날짜": datetime.now().strftime('%Y-%m-%d %H:%M'), 
            "과목": subject, 
            "등급": grade_level, 
            "관찰팩트(통합)": combined_eval, 
            "생성세특": final_text
        }]).to_excel(writer, index=False)
        
    st.download_button(
        label="📂 작성된 세특 엑셀로 다운로드 (개인 PC 보관)",
        data=output.getvalue(),
        file_name=f"{subject}_세특기록_{datetime.now().strftime('%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
