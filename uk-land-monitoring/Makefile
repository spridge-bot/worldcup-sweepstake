# Convenience targets. See SETUP.md for the full guide.
PY ?= python
PORT ?= 8000
AOI ?= config/aoi.example.geojson
START ?= 2023-01-01
END ?= 2024-12-31
SENSOR ?= s1
export PYTHONPATH = src

.PHONY: help install demo serve pipeline collections static clean

help:
	@echo "make demo       - regenerate demo data and serve the example dashboard"
	@echo "make serve       - serve the viewer (PORT=$(PORT))"
	@echo "make static      - build a standalone shareable dashboard HTML (no server)"
	@echo "make install     - pip install the geospatial deps (for the real pipeline)"
	@echo "make collections - list live OS NGD collection IDs (needs OS_API_KEY)"
	@echo "make pipeline    - real run: AOI=$(AOI) START=$(START) END=$(END) SENSOR=$(SENSOR)"

install:
	pip install -r requirements.txt

static:
	$(PY) scripts/build_static.py
	@echo "Open/share outputs/dashboard_demo.html (uses demo or outputs/ data)."

demo:
	$(PY) scripts/make_demo_timeseries.py
	$(PY) -m landmon.web.server --port $(PORT)

serve:
	$(PY) -m landmon.web.server --port $(PORT)

collections:
	$(PY) -m landmon.cli collections

pipeline:
	$(PY) -m landmon.cli pipeline --aoi $(AOI) --start $(START) --end $(END) \
		--sensor $(SENSOR) --chips --chip-mode rgb
	@echo "Done -> view with: make serve  (reads outputs/activity.geojson)"

clean:
	rm -rf outputs/chips outputs/*.geojson
