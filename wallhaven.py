import click
import re
import random
import requests
from pathlib import Path
from dataclasses import dataclass
from gi.repository import Gio
import aiohttp
import aiofiles
import asyncio
import backoff

from aiohttp import ClientSession


api_url = "https://wallhaven.cc/api/v1/search"

SORTING = ["random", "favourites", "toplist", "views"]
CATEGORIES = ["general", "anime", "people"]
PURITY = ["sfw", "sketchy", "nsfw"]


@dataclass
class Wallpaper:
    id: str
    url: str
    category: str
    purity: str
    destination_path: Path = None
    kind: str = "fresh"

    bgsetting = Gio.Settings.new("org.gnome.desktop.background")

    @property
    def filename(self):
        path = Path(self.destination_path, self.kind, self.category)
        suffix = Path(self.url).suffix
        fn = f"wallhaven-{self.id}-{self.purity}{suffix}"
        return path / fn

    @property
    def wallhaven_url(self):
        return f"https://wallhaven.cc/w/{self.id}"

    @backoff.on_exception(backoff.expo, aiohttp.ClientError, max_time=60)
    async def download(self, session):
        fn = self.filename
        fn.parent.mkdir(parents=True, exist_ok=True)

        async with session.get(self.url, raise_for_status=True) as response:
            async with aiofiles.open(fn, "wb") as f:
                async for data in response.content.iter_chunked(1024):
                    await f.write(data)
            print(f"Downloaded {self.url} -> {self.filename}")

    @classmethod
    def from_filepath(cls, filepath):
        path = Path(filepath)
        category = path.parts[-2]
        _, wallhavenid, purity = path.stem.split("-")
        wp = cls(
            wallhavenid, filepath, category, purity, path.parents[2], path.parts[-3]
        )
        wp.kind = path.parts[-3]
        return wp

    def set_as_background(self):
        self.bgsetting.set_string("picture-uri", f"file://{self.filename}")

    @classmethod
    def get_current(cls):
        bg = cls.bgsetting.get_string("picture-uri").replace("file://", "")
        return cls.from_filepath(bg)

    @classmethod
    def choose_random_background(cls, category, purity, destination):
        """Set a background image based on purity and category"""
        if destination is None:
            raise click.exceptions.Exit("Error: destination needs to be set")

        if not isinstance(purity, (list, tuple)):
            purity = [purity]

        regex = re.compile(r"^.*-({})\.\w+$".format("|".join(purity)))

        def get_images(prefix):
            image_path = Path(destination) / prefix
            for i in image_path.rglob("*.*"):
                *_, cat, fn = i.parts
                if cat in category and regex.match(fn):
                    yield i

        fresh_images = [i for i in get_images("fresh")]
        saved_images = [i for i in get_images("saved")]
        fresh_weights = [20] * len(fresh_images)
        saved_weights = [10] * len(saved_images)
        images = fresh_images + saved_images
        weights = fresh_weights + saved_weights
        try:
            choice = random.choices(images, weights=weights, k=1)[0]
            Wallpaper.from_filepath(choice).set_as_background()
        except IndexError:
            raise click.exceptions.Exit("Error: no images found")


@click.group()
def cli():
    pass


@cli.command()
@click.option(
    "--category",
    "-c",
    type=click.Choice(CATEGORIES),
    default=["general", "anime", "people"],
    multiple=True,
)
@click.option(
    "--purity", "-p", type=click.Choice(PURITY), default=["sfw"], multiple=True
)
@click.option(
    "--destination", type=click.Path(), nargs=1, envvar="WALLHAVEN_DESTINATION"
)
def choose_random_background(category, purity, destination):
    """Set a background image based on purity and category"""
    Wallpaper.choose_random_background(category, purity, destination)


@cli.command()
@click.option("--api-key", envvar="WALLHAVEN_API_KEY")
@click.option(
    "--sorting", "-s", default="random", show_default=True, type=click.Choice(SORTING)
)
@click.option(
    "--category",
    "-c",
    type=click.Choice(CATEGORIES),
    default=["general", "anime", "people"],
    multiple=True,
)
@click.option(
    "--purity", "-p", type=click.Choice(PURITY), default=["sfw"], multiple=True
)
@click.option(
    "--destination", type=click.Path(), nargs=1, envvar="WALLHAVEN_DESTINATION"
)
def get_wallpapers(api_key, sorting, category, purity, destination):
    """
    Query the API for wallpapers
    categories and purity are strings containing 1 or 0 to denote the category/purity level
    """

    if destination is None:
        raise click.exceptions.Exit("Error: destination needs to be set")
    category_string = "".join([str(int(c in category)) for c in CATEGORIES])
    purity_string = "".join([str(int(p in purity)) for p in PURITY])

    payload = {
        "apikey": api_key,
        "sorting": sorting,
        "categories": category_string,
        "purity": purity_string,
        "ratios": "16x9,16x10",
    }
    resp = requests.get(api_url, params=payload).json()

    wallpapers = [
        Wallpaper(i["id"], i["path"], i["category"], i["purity"], destination)
        for i in resp["data"]
    ]
    loop = asyncio.get_event_loop()
    loop.run_until_complete(download_wallpapers(wallpapers))


async def download_wallpapers(wallpapers):
    async with aiohttp.ClientSession() as session:
        tasks = [w.download(session) for w in wallpapers]
        return await asyncio.gather(*tasks)


@cli.command()
def show_wallpaper():
    """Display the path of the current background"""
    wp = Wallpaper.get_current()
    print(wp.filename)
    print(wp.wallhaven_url)


@cli.command()
def delete_wallpaper():
    """
    Delete the current background image and choose another with the same category/purity
    """
    wp = Wallpaper.get_current()
    if wp.kind != 'fresh':
        raise click.exceptions.Exit(f"Error: {wp.filename} has been saved.")
    if wp.filename is not None:
        wp.filename.unlink()
        Wallpaper.choose_random_background(wp.category, wp.purity, wp.destination_path)


@cli.command()
@click.option(
    "--destination", type=click.Path(), nargs=1, envvar="WALLHAVEN_DESTINATION"
)
def save_wallpaper(destination):
    """Save the current background to a different path"""
    saved = Path(destination) / "saved"
    bg = Wallpaper.get_current().filename
    dest = Path(saved, *bg.parts[-2:])
    dest.parent.mkdir(parents=True, exist_ok=True)
    bg.replace(dest)


if __name__ == "__main__":
    cli()
