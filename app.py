import streamlit as st
import streamlit.components.v1 as components
from time import perf_counter

from database import patent_count, search_patents


st.set_page_config(page_title="Patent Search", page_icon="🔎")
st.markdown('<div id="page-top"></div>', unsafe_allow_html=True)


if st.session_state.pop("scroll_to_top", False):
	components.html(
		"""
		<script>
		const resetScroll = () => {
			const document = window.parent.document;
			const pageTop = document.getElementById("page-top");
			if (pageTop) {
				pageTop.scrollIntoView({ block: "start", behavior: "auto" });
			}
			const scrollTargets = [
				document.scrollingElement,
				document.body,
				document.querySelector('[data-testid="stAppViewContainer"]'),
				document.querySelector('[data-testid="stAppViewContainer"] section.main'),
			];
			scrollTargets.filter(Boolean).forEach((element) => {
				element.scrollTop = 0;
			});
			window.parent.scrollTo(0, 0);
		};
		resetScroll();
		setTimeout(resetScroll, 100);
		setTimeout(resetScroll, 300);
		</script>
		""",
		height=1,
	)

st.title("Hello, world!")
st.write(f"Indexed {patent_count()} patent applications in SQLite.")

st.sidebar.header("Hybrid filters")
classification_prefix = st.sidebar.text_input(
	"Classification starts with", placeholder="B60B"
)
title_keyword = st.sidebar.text_input("Title contains")
abstract_keyword = st.sidebar.text_input("Abstract contains")
exact_title = st.sidebar.text_input("Exact title")
hybrid_enabled = st.sidebar.checkbox("Enable hybrid filters", value=True)

query = st.text_input("Search patents", placeholder="Try: vehicle wheel sensor")
has_filter_input = any(
	value.strip()
	for value in (
		classification_prefix,
		title_keyword,
		abstract_keyword,
		exact_title,
	)
)
if query.strip() or has_filter_input:
	search_key = (
		query,
		classification_prefix,
		title_keyword,
		abstract_keyword,
		exact_title,
		hybrid_enabled,
	)
	if st.session_state.get("last_search") != search_key:
		st.session_state.last_search = search_key
		st.session_state.result_page = 0

	page_size = 30
	page = st.session_state.get("result_page", 0)
	filters = {
		"classification_prefix": classification_prefix,
		"title_keyword": title_keyword,
		"abstract_keyword": abstract_keyword,
		"exact_title": exact_title,
	}
	baseline_start = perf_counter()
	search_patents(query, limit=page_size + 1, offset=0, hybrid=False)
	baseline_ms = (perf_counter() - baseline_start) * 1000

	hybrid_start = perf_counter()
	page_results = search_patents(
		query,
		limit=page_size + 1,
		offset=page * page_size,
		hybrid=hybrid_enabled,
		**filters,
	)
	hybrid_ms = (perf_counter() - hybrid_start) * 1000
	has_next_page = len(page_results) > page_size
	results = page_results[:page_size]

	st.subheader(f"Results (page {page + 1})")
	st.caption(
		f"Search time: {hybrid_ms:.2f} ms with hybrid mode | "
		f"{baseline_ms:.2f} ms without filters"
	)
	if not results:
		st.info("No matching patents found.")
	for result in results:
		with st.container(border=True):
			st.markdown(f"**{result['title']}**")
			st.caption(
				f"{result['doc_number']} | Classification: "
				f"{result['classification'] or 'Unavailable'}"
			)
			st.markdown(result["title_snippet"], unsafe_allow_html=True)
			if result["claims_snippet"]:
				st.caption("Matching claim")
				st.markdown(
					f"<div style=\"display:-webkit-box;-webkit-box-orient:"
					f"vertical;-webkit-line-clamp:4;overflow:hidden;line-height:1.5;\">"
					f"{result['claims_snippet']}</div>",
					unsafe_allow_html=True,
				)
			if result["description_snippet"]:
				st.caption("Matching description")
				st.markdown(
					f"<div style=\"display:-webkit-box;-webkit-box-orient:"
					f"vertical;-webkit-line-clamp:6;overflow:hidden;line-height:1.5;\">"
					f"{result['description_snippet']}</div>",
					unsafe_allow_html=True,
				)

	previous, page_label, next_page = st.columns([1, 2, 1])
	with previous:
		if st.button("Previous", disabled=page == 0):
			st.session_state.result_page = page - 1
			st.session_state.scroll_to_top = True
			st.rerun()
	with page_label:
		st.write(f"Page {page + 1}")
	with next_page:
		if st.button("Next", disabled=not has_next_page):
			st.session_state.result_page = page + 1
			st.session_state.scroll_to_top = True
			st.rerun()