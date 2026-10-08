/** Actual PDF.js text extraction and find projections for the disposable viewer.
 * Content-stream order and whole-item bounds are retained; no OCR is performed.
 */

/** @typedef {{str:string,transform:number[],width:number,height:number,hasEOL?:boolean}} TextItem */
/** @typedef {{text:string,start:number,end:number,rect:{x:number,y:number,w:number,h:number},eol:boolean}} TextRun */
/** @typedef {{page:number,text:string,search:string,runs:TextRun[]}} TextPage */
/** @typedef {{page:number,start:number,end:number,runs:TextRun[]}} TextHit */

/** Fold compatibility characters and case for literal search, without regex evaluation.
 * @param {string} text @returns {string}
 */
export function normalizeText(text) { return text.normalize('NFKC').toLocaleLowerCase(); }

/** Project horizontal PDF text items to page fractions and searchable offsets.
 * Extraction order is retained. Geometry adds a space only for a visible inline
 * gap, allowing contiguous CJK fragments to remain searchable.
 * @param {number} page @param {TextItem[]} items
 * @param {{width:number,height:number,scale:number,transform:number[]}} viewport
 * @param {(a:number[],b:number[])=>number[]} transform @returns {TextPage}
 */
export function projectPage(page,items,viewport,transform) {
  let text='',search='';
  /** @type {TextRun[]} */
  const runs=[];
  for(const item of items) {
    if(!item.str)continue;
    const matrix=transform(viewport.transform,item.transform),height=Math.hypot(matrix[2],matrix[3])||item.height*viewport.scale;
    const rect={x:matrix[4]/viewport.width,y:(matrix[5]-height)/viewport.height,w:item.width*viewport.scale/viewport.width,h:height/viewport.height};
    const previous=runs[runs.length-1];
    let gap='';
    if(previous) {
      const line=Math.abs(previous.rect.y-rect.y)>Math.max(previous.rect.h,rect.h)*0.6;
      const separated=rect.x-previous.rect.x-previous.rect.w>Math.min(previous.rect.h,rect.h)*0.12;
      gap=previous.eol||line?'\n':separated&&!/\s$/.test(previous.text)&&!/^\s/.test(item.str)?' ':'';
    }
    text+=gap+item.str;search+=gap;
    const start=search.length;search+=normalizeText(item.str);
    runs.push({text:item.str,start,end:search.length,rect,eol:!!item.hasEOL});
  }
  return {page,text,search,runs};
}

/** Extract a finite anonymous document using its actual PDF.js pages.
 * Bounds are checked before text projection; callers own and destroy the PDF.
 * @param {{numPages:number,getPage:(page:number)=>Promise<{getTextContent:()=>Promise<{items:TextItem[]}>,getViewport:(options:{scale:number})=>{width:number,height:number,scale:number,transform:number[]}}>}} pdf
 * @param {{transform:(a:number[],b:number[])=>number[]}} util
 * @returns {Promise<TextPage[]>}
 */
export async function extractPages(pdf,util) {
  if(pdf.numPages>12)throw new Error('Demo PDF page limit exceeded');
  /** @type {TextPage[]} */
  const pages=[];
  let characters=0;
  for(let index=1;index<=pdf.numPages;index++) {
    const page=await pdf.getPage(index),content=await page.getTextContent();
    const items=content.items.filter(item=>typeof item.str==='string');
    if(items.length>30000)throw new Error('Demo PDF text item limit exceeded');
    characters+=items.reduce((sum,item)=>sum+item.str.length,0);
    if(characters>200000)throw new Error('Demo PDF character limit exceeded');
    pages.push(projectPage(index,items,page.getViewport({scale:1}),util.transform));
  }
  return pages;
}

/** Enumerate each non-overlapping literal occurrence with its true page/item bounds.
 * A normalized query is bounded to 200 characters; an empty query has no hits.
 * @param {TextPage[]} pages @param {string} query @returns {TextHit[]}
 */
export function findHits(pages,query) {
  const needle=normalizeText(query.trim()).slice(0,200);
  /** @type {TextHit[]} */
  const hits=[];
  if(!needle)return hits;
  for(const page of pages) {
    let start=page.search.indexOf(needle);
    while(start>=0) {
      const end=start+needle.length;
      hits.push({page:page.page,start,end,runs:page.runs.filter(run=>run.end>start&&run.start<end)});
      start=page.search.indexOf(needle,end);
    }
  }
  return hits;
}
