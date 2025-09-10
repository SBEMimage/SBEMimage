# Automated Focus/Stigmator Series (AFSS)

AFSS optimizes focus and stigmation by applying small working distance or stigmator variations to tracked tiles across multiple cuts and analyzing resulting sharpness changes. It runs during acquisition without adding extra electron exposure. Starting focus/stigmation should be reasonably close to optimal.  

---

## How it works
- Each series of type **Focus**, **StigX**, or **StigY** runs during several slices in the following sequence:  
  *Autofocus → StigX → StigY → Autofocus …*  
  Triggered by **Interval N slices**. Autofocus can run alone if *AutoStigmator* is disabled.  
- Sharpness is measured using edge detection with a circular mask to exclude tile borders.  
- WD/Stig variations vs. sharpness are fit with a parabolic or linear model to estimate the optimum.  
- Resulting plots are saved in `/meta/stats` for optional inspection.  
- Fits with high RMSE or failed convergence are excluded automatically.  

---

## Consensus modes
- **Average mode** (default): applies averaged corrections across tiles.  
- **Specific mode**: applies per-tile corrections, mainly for rough initial estimations.  
- **Mixed mode**: e.g. *Specific: Focus, Average: Stig* for focus gradient corrections.  

---

## Practical notes
- **Number of WD/Stig variations:** three are sufficient; increase if reliability issues occur.  
- **Frequency:** For less-stable imaging, run more often (*Interval N slices* ~3–5).  
- **Tracking modes:** Recommended → *Track selected fit global*, *Track selected approx. others*.  
- **Stigmator:** Usually constant across reference tiles; avoid inducing gradients, especially in *Track selected, fit global* mode.  
- **Speed:** Disable drift correction if stage precision is better than ~10 µm and imaging is stable.  
- **Background mode:** Runs full AFSS without applying corrections.  
