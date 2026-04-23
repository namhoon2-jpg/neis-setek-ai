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

APP_PASSWORD = "1234" 
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
# 4. 화면 구성 및 사이드바
# ==========================================
st.title("📝 NEIS 세특 AI 어시스턴트 (V29: 자동 평가 하이브리드)")

with st.sidebar:
    st.header("📝 기본 정보")
    subject = st.text_input("과목명", placeholder="예: 미적분")
    grade_level = st.text_input("성취도/등급", placeholder="예: A")

    st.divider()
    st.header("📏 세특 분량 설정")
    target_bytes = st.slider("목표 절대 최대치 (Bytes)", min_value=500, max_value=1500, value=1500, step=100)
    st.session_state.target_bytes = target_bytes
    
    st.divider()
    st.header("🧠 AI 지식 저장소 (선택)")
    db_file = st.file_uploader("지식 추가 (Excel/PDF)", type=["xlsx", "pdf"])
    
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

    st.caption("현재 기억 상태")
    if st.button("🔄 최신 지식 불러오기", use_container_width=True):
        count = sync_with_gsheet()
        st.success(f"현재 총 {count}개의 지식 탑재.")

# ==========================================
# 메인 화면: 교사 관찰 및 평가
# ==========================================
st.subheader("👨‍🏫 교사 관찰 및 평가")
col1, col2 = st.columns(2)

with col1:
    # 💡 V29 핵심 1: AI 자동 평가 안내 멘트 반영
    report_eval = st.text_area(
        "📄 활동/탐구 역량 평가 (비워두면 AI 자동 평가)", 
        placeholder="보고서의 팩트는 AI가 추출합니다.\n\n특별히 강조하고 싶은 [교사 평가]가 있다면 적어주세요.\n(비워두시면 AI가 보고서를 바탕으로 논리력/분석력을 스스로 분석하여 평가하고, 내용을 적으시면 '선생님 평가 + AI 평가'가 융합됩니다.)", 
        height=180
    )

with col2:
    general_eval = st.text_area(
        "🧑‍🏫 교사의 인지적/인성 평가", 
        placeholder="학생의 지적 호기심, 끈기, 수업 태도 등 인지적 특성과 인성적 측면에 대한 종합 평가를 적어주세요. 세특의 마지막 결론으로 융합됩니다.\n(예: 실패를 두려워하지 않고 끊임없이 질문하며 원리를 탐구하는 태도를 지님)", 
        height=180
    )

pdf_files = st.file_uploader("학생 보고서 (PDF) - 여러 개 선택 가능", type=["pdf"], accept_multiple_files=True)

if st.session_state.authenticated and not st.session_state.db_texts and GSHEET_CSV_URL:
    sync_with_gsheet()

# ==========================================
# 5. 생성 엔진
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    # 이제 보고서만 올려도 작동할 수 있도록 유연성 강화 (과목명만 필수)
    if not subject:
        st.warning("👈 과목명을 입력해주세요.")
    else:
        with st.spinner("1/4: 학생 데이터를 분석 중입니다..."):
            student_report_text = ""
            if pdf_files:
                for idx, file in enumerate(pdf_files):
                    try:
                        with pdfplumber.open(file) as pdf:
                            report_content = ""
                            for pg in pdf.pages:
                                text = pg.extract_text()
                                if text: report_content += text + "\n"
                            student_report_text += f"\n--- [보고서 {idx+1}] ---\n{report_content}"
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
            [관찰 가능한 행동 동사] 내면 상태('이해함', '체득함', '깨달음') 절대 금지. 눈으로 확인 가능한 능동적 행동('증명함', '설명함', '분석함')으로 우회하세요.
            [자연스러운 서사] 동기-과정-결과-평가가 기계적인 나열이 아닌 인과관계로 매끄럽게 이어지게 설계하세요.
            [공통 가이드라인] {guidelines}
            위 규칙을 지켜 '{subject}' 과목의 세특 뼈대를 가상으로 작성하세요.
            """
            best_practice_template = model.generate_content(bp_prompt).text.strip()
            st.session_state.current_template = best_practice_template

        with st.spinner("4/4: 데이터 융합 및 팩트 기반 풍성한 서술 중..."):
            max_b = st.session_state.target_bytes
            min_b = int(max_b * 0.8)
            safe_max_c = int((max_b / 3) * 0.95) 
            min_c = int(min_b / 3)
            
            # 💡 V29 핵심 2: 프롬프트 내 조건부 평가 융합 지시
            prompt = f"""
            아래 [데이터]만을 활용하여 학생의 실제 NEIS 교과세특을 작성하세요.

            [데이터]
            - 과목명: {subject}
            - 성취도: {grade_level}
            - 교사의 보고서 역량 평가: {report_eval if report_eval.strip() else "(입력된 평가 없음)"}
            - 교사의 인지적/인성 평가: {general_eval if general_eval.strip() else "(입력된 평가 없음)"}
            - 학생 다중 보고서 텍스트(팩트 원천): {student_report_text[:2000]}

            [절대 모방 템플릿] 
            {best_practice_template}

            [🔥 대전제: 역할 분담 하이브리드 및 무결성 제어 🔥]
            1. 역할 분담 서사 (AI 자동 평가 적용): <학생 다중 보고서 텍스트>에서 탐구의 팩트(동기, 과정, 결과)를 추출하여 서술합니다. 이때 <교사의 보고서 역량 평가>가 입력되어 있다면 '선생님의 평가 + AI의 자체 분석 평가'를 융합하고, 만약 비어있다면 AI가 직접 보고서를 심층 분석하여 학생의 논리력, 분석력 등을 객관적으로 평가하여 덧붙이세요. 마지막으로 <교사의 인지적/인성 평가>가 있다면 글의 결론부에 묵직하게 배치하세요.
            2. 분량 및 팩트 보존 (매우 중요): 보고서 팩트를 단순 요약하거나 생략하지 말고, 한글 글자 수를 무조건 **최소 {min_c}자 이상, {safe_max_c}자 이하**가 되도록 풍성하게 꽉 채워 작성하세요. 글이 짧으면 실패입니다.
            3. 관찰 가능한 능동태 동사 강제: 내면 추측("이해함", "체득함", "깨달음") 금지. 반드시 관찰 가능한 능동 행동("~을 수학적으로 증명함", "~을 논리적으로 설명함")으로 서술하세요.
            4. 상투적 표현 철폐: "~활동을 통해", "~뿐만 아니라", "탁월한 역량을 보여줌" 등 AI 특유의 식상한 전환어와 감정적 찬양을 완벽히 배제하세요. 오직 건조한 팩트와 객관적 평가만 남기세요.
            5. 완벽한 음슴체: 모든 수식은 한글로 풀고, 문장 끝은 명사형 종결어미(~함, ~임, ~됨 등)로 끝내세요. 앞뒤 태그(제목 등) 절대 금지.
            """
            response = model.generate_content(prompt)
            st.session_state.current_result = response.text.strip().replace('\n', ' ')

# ==========================================
# 6. 결과 출력 및 멸균 작업
# ==========================================
if st.session_state.current_result:
    res_text = st.session_state.current_result
    
    tags_to_remove = [f"[{subject}]", f"{subject}", "세특 우수 사례:", "가상 세특:", "최종 세특:", "1. ", "동기:", "탐구 과정:"]
    for tag in tags_to_remove:
        if res_text.startswith(tag):
            res_text = res_text[len(tag):].strip()

    forbidden_replacements = {
        "이 학생은 ": "",
        "본 학생은 ": "",
        "학생은 ": "",
        "자신은 ": "",
        "교과세특": "기록",
        "세특": "기록",
        "생기부": "기록",
        "학교생활기록부": "기록",
        "체득함": "적용함",
        "이해함": "설명함",
        "깨달음": "분석함"
    }
    for bad_word, good_word in forbidden_replacements.items():
        res_text = res_text.replace(bad_word, good_word)

    st.session_state.current_result = res_text

    st.divider()
    st.subheader("🎯 생성된 맞춤형 세특 (AI 하이브리드 평가 반영)")
    
    byte_len = get_byte_length(res_text)
    max_target = st.session_state.target_bytes
    min_target = int(max_target * 0.8)
    
    if byte_len > max_target: 
        st.error(f"⚠️ 분량 초과: {byte_len} / 최대 {max_target} Bytes (내용이 너무 풍부합니다. 불필요한 문장을 쳐내주세요.)")
    elif byte_len < min_target:
        st.warning(f"⚠️ 분량 미달: {byte_len} Bytes (목표 최소치 {min_target} Bytes). 보고서 내용을 더 상세히 추가해 주세요.")
    else: 
        st.success(f"✅ 완벽 분량 달성: {byte_len} Bytes (목표 타겟: {min_target} ~ {max_target} Bytes 안착)")
    
    final_text = st.text_area("결과 확인/수정", value=res_text, height=250)

    with st.expander("🔍 AI가 설계한 뼈대 훔쳐보기 (참고용)"):
        st.info(st.session_state.current_template)

    # 💡 V29 핵심 3: 엑셀 저장 시 빈칸 자동 평가 여부 기록
    report_eval_record = report_eval if report_eval.strip() else "(보고서 기반 AI 자동 평가)"
    general_eval_record = general_eval if general_eval.strip() else "(미기재)"
    combined_eval = f"[탐구 역량] {report_eval_record}\n[인지/인성] {general_eval_record}"
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame([{
            "날짜": datetime.now().strftime('%Y-%m-%d %H:%M'), 
            "과목": subject, 
            "등급": grade_level, 
            "종합평가내용": combined_eval, 
            "생성세특": final_text
        }]).to_excel(writer, index=False)
        
    st.download_button(
        label="📂 작성된 세특 엑셀로 다운로드 (개인 PC 보관)",
        data=output.getvalue(),
        file_name=f"{subject}_세특기록_{datetime.now().strftime('%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
