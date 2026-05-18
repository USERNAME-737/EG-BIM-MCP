;;;============================================================
;;; MINI - 다중 이미지 한줄 삽입 (PowerShell 다중선택)
;;; eg-bim / IntelliCAD 9.x 호환 (ACTIVE X 미사용)
;;;============================================================

(defun MINI:fname (path / i ch result)
  (setq result path)
  (setq i (strlen path))
  (while (> i 0)
    (setq ch (substr path i 1))
    (if (or (= ch "\\") (= ch "/"))
      (progn (setq result (substr path (1+ i))) (setq i 0))
    )
    (setq i (1- i))
  )
  result
)

(defun MINI:trimslash (s)
  (if (and (> (strlen s) 0)
           (or (= (substr s (strlen s) 1) "\\")
               (= (substr s (strlen s) 1) "/")))
    (substr s 1 (1- (strlen s)))
    s
  )
)

(defun MINI:multiselect (/ tmpdir tmpps tmptxt fp line result)
  (setq tmpdir (MINI:trimslash (getenv "TEMP")))
  (setq tmpps  (strcat tmpdir "/" "mini_select.ps1"))
  (setq tmptxt (strcat tmpdir "/" "mini_files.txt"))

  (setq fp (open tmpps "w"))
  (write-line "Add-Type -AssemblyName System.Windows.Forms" fp)
  (write-line "$d = New-Object System.Windows.Forms.OpenFileDialog" fp)
  (write-line "$d.Multiselect = $true" fp)
  (write-line "$d.Filter = 'Images (*.jpg;*.jpeg;*.png)|*.jpg;*.jpeg;*.png'" fp)
  (write-line "$d.Title = 'MINI - Image Select (Ctrl+Click)'" fp)
  (write-line (strcat "$out = '" tmptxt "'") fp)
  (write-line "if ($d.ShowDialog() -eq 'OK') {" fp)
  (write-line "  [System.IO.File]::WriteAllLines($out, $d.FileNames, [System.Text.Encoding]::Default)" fp)
  (write-line "} else {" fp)
  (write-line "  [System.IO.File]::WriteAllText($out, '')" fp)
  (write-line "}" fp)
  (close fp)

  (startapp "powershell.exe"
    (strcat "-NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File \""
            tmpps "\""))

  (princ "\n[대화상자에서 파일 선택 후 OK 누르고 여기서 Enter]")
  (getstring "\nEnter: ")

  (setq result (quote ()))
  (setq fp (open tmptxt "r"))
  (if fp
    (progn
      (while (setq line (read-line fp))
        (if (and (> (strlen line) 0) (= (ascii line) 65279))
          (setq line (substr line 2))
        )
        (if (and (> (strlen line) 0)
                 (= (ascii (substr line (strlen line) 1)) 13))
          (setq line (substr line 1 (1- (strlen line))))
        )
        (if (> (strlen line) 3)
          (setq result (append result (list line)))
        )
      )
      (close fp)
    )
    (princ "\n[MINI] 결과 파일 없음")
  )
  result
)

(defun c:MINI (/ pt wid gap files f idx ent edata u11 s13
               curr_w sf x_off y_off n x y oldecho dir scaled_h)

  (princ "\n== MINI: 다중 이미지 한줄 삽입 ==")
  (princ "\n대화상자를 실행합니다...")

  (setq files (MINI:multiselect))

  (if (null files)
    (princ "\n선택된 파일이 없습니다.")
    (progn
      (princ (strcat "\n총 " (itoa (length files)) "장 선택됨."))
      (setq idx 0)
      (repeat (length files)
        (princ (strcat "\n  [" (itoa (1+ idx)) "] " (MINI:fname (nth idx files))))
        (setq idx (1+ idx))
      )

      (setq pt (getpoint "\n삽입 기준점(좌하단) 지정: "))
      (if (null pt)
        (princ "\n취소됨.")
        (progn
          (initget 6)
          (setq wid (getreal "\n이미지 1장 폭 (도면단위): "))
          (if (null wid)
            (princ "\n취소됨.")
            (progn
              (initget 4)
              (setq gap (getreal
                (strcat "\n이미지 간격 <" (rtos (* wid 0.1) 2 1) ">: ")))
              (if (null gap) (setq gap (* wid 0.1)))

              (initget "R L U D")
              (setq dir (getkword "\n배치방향[R/L/U/D]<R>: "))
              (if (null dir) (setq dir "R"))

              (setq oldecho (getvar "cmdecho"))
              (setvar "cmdecho" 0)
              (command "_.undo" "_begin")
              (setq x_off 0.0  y_off 0.0  n 0  idx 0)

              (repeat (length files)
                (setq f (nth idx files))
                (setq idx (1+ idx))
                (cond
                  ((= dir "R") (setq x (+ (car pt) x_off)  y (cadr pt)))
                  ((= dir "L") (setq x (- (car pt) x_off wid)  y (cadr pt)))
                  ((= dir "U") (setq x (car pt)  y (+ (cadr pt) y_off)))
                  ((= dir "D") (setq x (car pt)  y (- (cadr pt) y_off)))
                )

                (command "-imageattach" f (list x y 0.0) 1.0 0)

                (setq ent (entlast))
                (setq edata (entget ent))
                (setq u11 (cdr (assoc 11 edata)))
                (setq s13 (cdr (assoc 13 edata)))

                (if (and u11 s13 (> (abs (car s13)) 0))
                  (progn
                    (setq curr_w (* (abs (car u11)) (abs (car s13))))
                    (if (> curr_w 0)
                      (progn
                        (setq sf (/ wid curr_w))
                        (command "_.scale" ent "" (list x y) sf)
                        (if (or (= dir "R") (= dir "L"))
                          (setq x_off (+ x_off wid gap))
                          (progn
                            (setq scaled_h (* wid (/ (float (abs (cadr s13))) (float (abs (car s13))))))
                            (setq y_off (+ y_off scaled_h gap))
                          )
                        )
                        (setq n (1+ n))
                        (princ (strcat "\r  " (itoa n) "/" (itoa (length files))
                                       " OK: " (MINI:fname f)))
                      )
                      (princ (strcat "\n  [FAIL] " (MINI:fname f)))
                    )
                  )
                  (progn
                    (princ (strcat "\n  [WARN] " (MINI:fname f)))
                    (if (or (= dir "R") (= dir "L"))
                      (setq x_off (+ x_off wid gap))
                      (setq y_off (+ y_off wid gap))
                    )
                    (setq n (1+ n))
                  )
                )
              )

              (command "_.undo" "_end")
              (setvar "cmdecho" oldecho)
              (command "_.zoom" "_e")
              (princ (strcat "\n\n== 완료: " (itoa n) "장 삽입 =="
                             "\n   폭=" (rtos wid 2 1)
                             "  간격=" (rtos gap 2 1)))
            )
          )
        )
      )
    )
  )
  (princ)
)

(princ "\n[Mini for EG-BIM. Programmed by KDJ]\n")
(princ)
