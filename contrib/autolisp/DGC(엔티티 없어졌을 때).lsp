;; ============================================================================
;; DGC - DXF Garbage Cleaner v2.1 (perf-tuned)
;; AutoCAD -> IntelliCAD migrated drawings: clean abnormal DXF group values
;; ----------------------------------------------------------------------------
;; Command: DGC
;;   Step 1) Entity type filter [All/Line/Vport/Text/Mtext/Polyline/Insert]
;;   Step 2) Region [All/Window]
;; ----------------------------------------------------------------------------
;; Safe-fix rules:
;;   group 10/11/12/13 Z component     -> 0.0   (any entity)
;;   group 38, 39                       -> 0.0
;;   group 50~58 (angle)                -> 0.0
;;   group 60 (invisible)               -> 0
;;   group 62 (color)                   -> 256 (ByLayer)
;;   group 70~78 (16-bit flag)          -> logand 65535
;;   group 90 (VIEWPORT only)           -> logand 65535
;;   group 210 (extrusion vector)       -> (0 0 1)
;; Report only (no auto-fix):
;;   group 40~49 (real, ambiguous)
;;   group 91~99 / 90 on non-VIEWPORT (count-like)
;; ============================================================================

;; ---------- abnormality predicates ------------------------------------------

(defun DGC:abZ (pt / z)
  (and (listp pt)
       (setq z (caddr pt))
       (numberp z)
       (> (abs z) 1.0e10)))

(defun DGC:abReal (v)
  (and (numberp v) (> (abs v) 1.0e10)))

(defun DGC:abFlag16 (v)
  (and (numberp v) (or (< v 0) (> v 65535))))

(defun DGC:abLong (v)
  (and (numberp v) (or (< v 0) (> v 2147483647))))

(defun DGC:abColor (v)
  (and (numberp v) (or (< v -256) (> v 256))))

(defun DGC:abInvis (v)
  (and (numberp v) (not (or (= v 0) (= v 1)))))

(defun DGC:abUnitComp (v)
  (and (numberp v) (> (abs v) 1.0001)))

;; ---------- value -> CSV string ---------------------------------------------

(defun DGC:val-str (v)
  (cond
    ((null v) "nil")
    ((numberp v)
      (if (and (< (abs v) 2.0e9) (equal v (fix v) 1.0e-9))
        (itoa (fix v))
        (rtos v 2 6)))
    ((= (type v) 'STR) v)
    ((and (listp v) (= (length v) 3))
      (strcat "(" (DGC:val-str (car v)) " "
                  (DGC:val-str (cadr v)) " "
                  (DGC:val-str (caddr v)) ")"))
    ((listp v) "(list)")
    (T "?")))

;; ---------- per-entity inspection -------------------------------------------
;; Returns list of (code old reason fix_or_nil)
;; Optimized: dispatch by code range first, skip non-relevant pairs immediately

(defun DGC:check (ed / type fdg code val pair)
  (setq type (cdr (assoc 0 ed)))
  (setq fdg '())
  (foreach pair ed
    (setq code (car pair))
    (setq val  (cdr pair))
    (cond
      ;; fast cut: codes outside any rule range
      ((or (< code 10) (> code 210)) nil)

      ;; 10~16 : point Z out of range
      ;; VIEWPORT은 reactor chain에 묶여 있어 entmod 시 화면 캐시 손상. 점 좌표 일체 건드리지 않음.
      ((<= code 16)
        (if (and (DGC:abZ val) (/= type "VIEWPORT"))
          (setq fdg (cons (list code val "Z_OUT_OF_RANGE"
                                (list (car val) (cadr val) 0.0)) fdg))))

      ;; 38, 39 : real -> 0.0
      ((<= code 39)
        (if (and (or (= code 38) (= code 39)) (DGC:abReal val))
          (setq fdg (cons (list code val "REAL_OUT_OF_RANGE" 0.0) fdg))))

      ;; 40~49 : report only
      ((<= code 49)
        (if (DGC:abReal val)
          (setq fdg (cons (list code val "REAL_REPORT_ONLY" nil) fdg))))

      ;; 50~58 : angle -> 0.0
      ;; VIEWPORT은 view twist(51) 등 화면에 영향 -> 스킵
      ((<= code 58)
        (if (and (DGC:abReal val) (/= type "VIEWPORT"))
          (setq fdg (cons (list code val "ANGLE_OUT_OF_RANGE" 0.0) fdg))))

      ;; 60 : invisible flag
      ((= code 60)
        (if (DGC:abInvis val)
          (setq fdg (cons (list code val "INVIS_FLAG" 0) fdg))))

      ;; 62 : color
      ((= code 62)
        (if (DGC:abColor val)
          (setq fdg (cons (list code val "COLOR_OUT_OF_RANGE" 256) fdg))))

      ;; 70~78 : 16-bit flag (VIEWPORT은 90만 처리)
      ((and (>= code 70) (<= code 78))
        (if (and (DGC:abFlag16 val) (/= type "VIEWPORT"))
          (setq fdg (cons (list code val "FLAG16_OUT_OF_RANGE"
                                (logand (fix val) 65535)) fdg))))

      ;; 90~99 : VIEWPORT 90 -> fix, others report only
      ((and (>= code 90) (<= code 99))
        (cond
          ((and (= code 90) (= type "VIEWPORT") (DGC:abFlag16 val))
            (setq fdg (cons (list code val "VPORT_FLAG90"
                                  (logand (fix val) 65535)) fdg)))
          ((and (/= type "VIEWPORT") (DGC:abLong val))
            (setq fdg (cons (list code val "LONG_REPORT_ONLY" nil) fdg)))))

      ;; 210 : extrusion vector
      ((= code 210)
        (if (and (listp val) (= (length val) 3)
                 (or (DGC:abUnitComp (car val))
                     (DGC:abUnitComp (cadr val))
                     (DGC:abUnitComp (caddr val))))
          (setq fdg (cons (list code val "EXTRUSION_OUT_OF_RANGE"
                                '(0.0 0.0 1.0)) fdg))))))
  fdg)

;; ---------- write CSV row ---------------------------------------------------

(defun DGC:write-row (f h type layer entry)
  (write-line
    (strcat
      (if h h "?") ","
      (if type type "?") ","
      (if layer layer "?") ","
      (itoa (car entry)) ","
      (DGC:val-str (cadr entry)) ","
      (caddr entry) ","
      (if (cadddr entry) (DGC:val-str (cadddr entry)) "(report)"))
    f))

;; ---------- apply fix to entity data ----------------------------------------
;; One-pass: build fix table, walk ed once via mapcar (no repeated subst)

(defun DGC:apply-fix (ed findings / fix-tbl cnt new rep)
  (setq fix-tbl '())
  (foreach entry findings
    (if (cadddr entry)
      (setq fix-tbl (cons (cons (car entry) (cadddr entry)) fix-tbl))))
  (setq cnt 0)
  (if fix-tbl
    (setq new
      (mapcar
        '(lambda (pair)
           (if (setq rep (assoc (car pair) fix-tbl))
             (progn
               (setq fix-tbl (DGC:remove-first rep fix-tbl))
               (setq cnt (1+ cnt))
               (cons (car pair) (cdr rep)))
             pair))
        ed))
    (setq new ed))
  (list new cnt))

(defun DGC:remove-first (item lst / out found)
  (setq found nil out '())
  (foreach x lst
    (if (and (not found) (equal x item))
      (setq found T)
      (setq out (cons x out))))
  (reverse out))

;; ---------- window predicate (LISP-side, ignores screen graphics) ----------
;; Optimized: peek (assoc 10 ed) only; sufficient for typical entities

(defun DGC:in-window (ed xmin xmax ymin ymax / p x y)
  (cond
    ((setq p (cdr (assoc 10 ed)))
      (if (and (listp p) (numberp (car p)) (numberp (cadr p)))
        (progn
          (setq x (car p) y (cadr p))
          (and (>= x xmin) (<= x xmax)
               (>= y ymin) (<= y ymax)))
        T))
    (T T)))

;; ---------- type-choice -> ssget filter ------------------------------------

(defun DGC:type-filter (kw)
  (cond
    ((= kw "Line")     '((0 . "LINE")))
    ((= kw "Vport")    '((0 . "VIEWPORT")))
    ((= kw "Text")     '((0 . "TEXT,MTEXT")))
    ((= kw "Mtext")    '((0 . "MTEXT")))
    ((= kw "Polyline") '((0 . "LWPOLYLINE,POLYLINE")))
    ((= kw "Insert")   '((0 . "INSERT")))
    (T nil)))

;; ============================================================================
;; DGC - main command
;; ============================================================================

(defun c:DGC ( / tkw rkw flt curtab is_model
                    pt1 pt2 xmin xmax ymin ymax
                    ss n i en ed g67 g410 fdg pair
                    fixed total ent_cnt scanned f tag
                    h ty ly t0 t1)
  ;; --- Step 1: entity type ---
  (initget "All Line Vport Text Mtext Polyline Insert")
  (setq tkw (getkword
    "\nEntity type [All/Line/Vport/Text/Mtext/Polyline/Insert] <All>: "))
  (if (null tkw) (setq tkw "All"))
  (setq flt (DGC:type-filter tkw))

  ;; --- Step 2: region ---
  (initget "All Window")
  (setq rkw (getkword "\nRegion [All/Window] <All>: "))
  (if (null rkw) (setq rkw "All"))

  ;; --- current layout (Model or paper layout name) ---
  (setq curtab (getvar "CTAB"))
  (setq is_model (= (strcase curtab) "MODEL"))
  (princ (strcat "\n[DGCFIX] current tab: " curtab))

  ;; --- window setup ---
  (if (= rkw "Window")
    (progn
      (setq pt1 (getpoint "\nFirst corner: "))
      (setq pt2 (getcorner pt1 "\nOpposite corner: "))
      (setq xmin (min (car pt1) (car pt2)))
      (setq xmax (max (car pt1) (car pt2)))
      (setq ymin (min (cadr pt1) (cadr pt2)))
      (setq ymax (max (cadr pt1) (cadr pt2)))
      (princ (strcat "\n[DGCFIX] window: ("
                     (rtos xmin 2 2) "," (rtos ymin 2 2) ") -> ("
                     (rtos xmax 2 2) "," (rtos ymax 2 2) ")"))))

  ;; --- selection: ssget "X" (database-wide; ignores screen graphics) ---
  ;; layout filter pushed into ssget for paper space
  (if (and (not is_model))
    (setq flt (append flt (list '(67 . 1) (cons 410 curtab)))))
  (princ "\n[DGCFIX] scanning database...")
  (setq ss (if flt (ssget "X" flt) (ssget "X")))

  (if (null ss)
    (princ "\n[DGCFIX] no entities matched")
    (progn
      (setq tag (strcat tkw "_" rkw "_" curtab))
      (setq f (open "C:\\temp\\dgc_fix.csv" "w"))
      (write-line (strcat "# tag=" tag) f)
      (write-line "handle,type,layer,code,old_value,reason,applied_fix" f)
      (setq total 0  ent_cnt 0  fixed 0  scanned 0)
      (setq n (sslength ss))
      (princ (strcat "\n[DGCFIX] candidates: " (itoa n)))
      (setq i 0)
      (while (< i n)
        (setq en (ssname ss i))
        ;; xdata는 entmod가 자동 보존(DB에 그대로 둠). '("*") 시도는 IntelliCAD에서 bad function 유발.
        (setq ed (entget en))
        ;; layout filter (only model-space side; paper handled by ssget)
        (if (if is_model
              (progn
                (setq g67 (cdr (assoc 67 ed)))
                (or (null g67) (= g67 0)))
              T)
          ;; window filter
          (if (or (= rkw "All")
                  (DGC:in-window ed xmin xmax ymin ymax))
            (progn
              (setq scanned (1+ scanned))
              (setq fdg (DGC:check ed))
              (if fdg
                (progn
                  (setq ent_cnt (1+ ent_cnt))
                  ;; cache header fields once per entity
                  (setq h  (cdr (assoc 5 ed))
                        ty (cdr (assoc 0 ed))
                        ly (cdr (assoc 8 ed)))
                  (foreach entry fdg
                    (setq total (1+ total))
                    (DGC:write-row f h ty ly entry))
                  (setq pair (DGC:apply-fix ed fdg))
                  (if (> (cadr pair) 0)
                    (progn
                      (entmod (car pair))
                      (setq fixed (+ fixed (cadr pair))))))))))
        (setq i (1+ i)))
      (close f)
      (command "_.REGENALL")
      (command "_.REDRAWALL")
      ;; VIEWPORT fix 후 view 캐시 재생성: TILEMODE 토글이 가장 확실
      ;; 1 -> Model space 강제 진입, 0 -> 직전 layout 복귀. 모든 viewport 내부 view 재초기화.
      (if (and (not is_model) (> fixed 0))
        (progn
          (setvar "TILEMODE" 1)
          (setvar "TILEMODE" 0)))
      (princ (strcat "\n[DGCFIX] tag:                    " tag))
      (princ (strcat "\n[DGCFIX] scanned (after filter): " (itoa scanned)))
      (princ (strcat "\n[DGCFIX] entities w/ findings:   " (itoa ent_cnt)))
      (princ (strcat "\n[DGCFIX] total findings:         " (itoa total)))
      (princ (strcat "\n[DGCFIX] auto-fixed values:      " (itoa fixed)))
      (princ (strcat "\n[DGCFIX] report-only values:     " (itoa (- total fixed))))
      (princ "\n[DGCFIX] file: C:\\temp\\dgc_fix.csv")
      (if (> fixed 0)
        (princ "\n[DGCFIX] tip: view 캐시가 깨져 보이면 도면 닫고 다시 여세요"))))
  (princ))

(princ "\n[DGC v2.1]_DXF GARBAGE CLEANER_KDJ")
(princ)
