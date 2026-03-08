.PHONY: build clean export serve

export:
	uv run python export.py

build: export
	zola build

serve: export
	zola serve

clean:
	rm -rf content/ public/
