/** Prototype-only declarations of the classic globals supplied by the actual
 * assembled viewer. They reuse native wire/screen types, and are not packaged. */

/** The active native document visit and its server-authoritative metadata. */
declare let META: Meta | null;
declare let DOC: string | null;
declare let DEFAULT_DOC: string;
declare let SHOW_ALL: boolean;
/** Native state tables retain their deployed string values in this prototype. */
declare const KIND_REQ: {readonly FIX:'fix';readonly QUESTION:'question'};
declare const ROLE: {readonly AGENT:'agent'};
declare const NOTICE_KIND: {readonly INFO:'info'};
declare const NOTICE_HOST: {readonly REVIEW:'review';readonly LIST:'list'};
/** Native participant and list/composer state remain the actual owners. */
declare const SEC: {open:boolean;review:boolean;done:boolean};
declare const OPEN_CARDS: Set<number>;
declare const ASSIGN_NEW: {v:string;touched:boolean};
declare let KIND_NEW: string;
declare const COMPOSE: {current:NativeDemoSelection|null;box:HTMLElement|null};
declare const REV: {target:{id:number}|null};
declare let REPLY: ReplyBox | null;
/** Native render seams are replaced only in the isolated local prototype. */
declare let drawPins: ()=>void;
declare let renderComposer: ()=>void;
declare let renderAssignNew: ()=>void;
declare let renderReplyOutcome: ()=>void;
declare let revTargetActs: ()=>void;
declare let drawSelPop: ()=>void;
declare let cancelSelection: (clearNote?:boolean)=>void;
declare let syncComposeSaveButtons: ()=>void;
declare let refreshDoc: (meta?:Meta)=>Promise<void>;
/** Native public screen commands and projections keep their actual outcomes. */
declare function closeSelPop(): void;
declare function setKind(value:string): void;
declare function saveDraftSoon(): void;
declare function setSelMode(value:boolean): void;
declare function isMe(person?:Person): boolean;
declare function isHuman(): boolean;
declare function canConfirmReview(): boolean;
declare function listReview(): Pin[];
declare function replyNote(reply:ReplyBox): HTMLTextAreaElement;
declare function loadPins(): Promise<boolean>;
declare function jumpToCard(id:number): void;
declare function showChange(id:number): Promise<void>;
declare function revBack(): void;
declare function lineNote(text:string,kind:string): unknown;
/** Only seeded API commands are accepted by native-fixture.js; no request is
 * forwarded to a production instance. This declaration covers this spike's use. */
declare function api(url:string,options:{method:string;body?:Record<string,unknown>;what:string;where:string;expect?:number[]}): Promise<{data:{ok?:boolean};status:number}>;

/** Native visit guards bind all asynchronous proposal effects to their initiating document. */
declare function captureVisit(): {doc:string|null;seq:number};
declare function currentVisit(visit:{doc:string|null;seq:number}): boolean;
/** Native command seams preserve keyboard/undo behavior in the isolated demo. */
declare let savePin: ()=>Promise<void>;
declare let appendToPin: (id:number,text:string)=>Promise<void>;
declare let pick: (request:Record<string,unknown>)=>Promise<void>;
declare let goPage: (value?:string)=>void;
declare let jumpPin: (id:number)=>void;
declare let switchDoc: (key:string)=>Promise<void>;
declare function confirmPin(id:number): void;
declare const CONFIRMING: Set<number>;

/** Native pending undo rows keep their owning section visible. */
declare function offersIn(section:string): boolean;

/** Reuse native approximate ETA and delayed-work wording in collapsed cards. */
declare function claimInfo(pin:Pin): {t:string;late:boolean;tip:string};

/** Native uncovered page geometry excludes sheets and overlay panels. */
declare function selPopArea(): {left:number;top:number;right:number;bottom:number};
/** Validate a requested native document switch before parking a draft. */
declare function docInfo(key:string): DocEntry|null;
/** Bundled icon markup is the only markup passed to the native rendering sink. */
declare class Html {text:string;toString():string;}
/** Return trusted native markup for a fixed bundled icon name. */
declare function ic(name:string): Html;
/** Render only native Html values; fixture names and notes use textContent. */
declare function setHtml(element:HTMLElement,markup:Html): void;

/** Native mention resolution and geometry reused only by the isolated inline candidate. */
declare const ASSIGNEE_AGENT: 'agent';
declare const MENTION: {ta:HTMLTextAreaElement|null;items:PersonSeen[];start:number;sel:number};
declare let defaultAssignee: (text:string,kind:string,hints?:Set<string>)=>string;
declare let mentionApply: (index:number)=>void;
declare let mentionPreview: (textarea:HTMLTextAreaElement)=>void;
declare let mentionGuard: (textarea:HTMLTextAreaElement)=>Element|null;
declare let openSelPop: (box:HTMLElement)=>void;
declare function mentionScan(text:string,hints?:Set<string>): {hit:string[];bad:string[];first:string|null};
declare function mentionHints(textarea:HTMLTextAreaElement): string[];
declare function mentionUpdate(textarea:HTMLTextAreaElement): void;
declare function peopleName(login:string): string;
declare function meLogin(): string;
declare function autoGrow(textarea:HTMLTextAreaElement): void;
declare function qHint(element:HTMLElement,text:string,kind:string): void;
declare function placeSelPop(): void;
