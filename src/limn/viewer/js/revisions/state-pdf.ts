// PDF.js resources held by the current comparison.
interface ComparisonPdfState {
  doc: PdfDocument | null;
  loading: PdfLoadingTask | null;
  observer: IntersectionObserver | null;
  tasks: Set<PdfRenderTask>;
}
const COMPARISON_PDF: ComparisonPdfState = {
  doc: null,
  loading: null,
  observer: null,
  tasks: new Set(),
};

/** Release the previous comparison's rendering tasks, loading request and document. */
function releaseComparisonPdf() {
  if (COMPARISON_PDF.observer) {
    COMPARISON_PDF.observer.disconnect();
    COMPARISON_PDF.observer = null;
  }
  COMPARISON_PDF.tasks.forEach((task) => {
    try {
      task.cancel();
    } catch (error) {}
  });
  COMPARISON_PDF.tasks.clear();
  if (COMPARISON_PDF.loading) {
    try {
      void COMPARISON_PDF.loading.destroy().catch(() => {});
    } catch (error) {}
    COMPARISON_PDF.loading = null;
  }
  COMPARISON_PDF.doc = null;
}

/** Keep the active PDF.js request so a change of visit can destroy it. */
function setComparisonLoading(loading: PdfLoadingTask) {
  COMPARISON_PDF.loading = loading;
}
/** Keep the PDF associated with the completed request until the view releases it. */
function setComparisonDocument(pdf: PdfDocument) {
  COMPARISON_PDF.doc = pdf;
}

export { COMPARISON_PDF, releaseComparisonPdf, setComparisonLoading, setComparisonDocument };
