import { mkdir, readFile, writeFile } from "node:fs/promises";
import { geoContains } from "d3-geo";

const geoDirectory = new URL("../public/geo/", import.meta.url);
const countriesPath = new URL("../public/geo/countries.geojson", import.meta.url);
const dotsPath = new URL("../public/geo/land-dots.json", import.meta.url);
const coastlinePath = new URL("../public/geo/coastline-50m.json", import.meta.url);
const landUrl =
  "https://raw.githubusercontent.com/martynafford/natural-earth-geojson/refs/heads/master/50m/physical/ne_50m_land.json";

// Natural Earth 1:50m land vectors are public domain.
const landResponse = await fetch(landUrl);
if (!landResponse.ok) throw new Error(`Natural Earth download failed (${landResponse.status})`);
const landGeoJson = await landResponse.json();
const countriesGeoJson = JSON.parse(await readFile(countriesPath, "utf8"));
const land = landGeoJson;
const france = countriesGeoJson.features.find((feature) => feature.properties.name === "France");
const ghana = countriesGeoJson.features.find((feature) => feature.properties.name === "Ghana");
if (!france || !ghana) throw new Error("France and Ghana must exist in countries.geojson");

const round = (value) => Math.round(value * 100) / 100;

function sampleLand(step) {
  const dots = [];
  for (let lat = -90 + step / 2; lat < 90; lat += step) {
    const longitudeStep = step / Math.cos((lat * Math.PI) / 180);
    for (let lng = -180; lng < 180; lng += longitudeStep) {
      const coordinate = [lng, lat];
      if (!geoContains(land, coordinate)) continue;
      const corridor = geoContains(france, coordinate) || geoContains(ghana, coordinate);
      dots.push([round(lat), round(lng), corridor ? 1 : 0]);
    }
  }
  return dots;
}

function ringsOf(geometry) {
  if (geometry.type === "Polygon") return geometry.coordinates;
  if (geometry.type === "MultiPolygon") return geometry.coordinates.flat();
  return [];
}

const features =
  landGeoJson.type === "FeatureCollection" ? landGeoJson.features : [landGeoJson];
const coastlines = features.flatMap((feature) =>
  ringsOf(feature.geometry)
    .map((ring) => {
      const points = [];
      for (const [lng, lat] of ring) {
        const point = [round(lat), round(lng)];
        const previous = points.at(-1);
        if (!previous || previous[0] !== point[0] || previous[1] !== point[1]) {
          points.push(point);
        }
      }
      if (points.length < 12) return [];
      const simplified = points.filter((_, index) => index % 2 === 0);
      const first = simplified[0];
      const last = simplified.at(-1);
      if (first[0] !== last[0] || first[1] !== last[1]) simplified.push(first);
      return [simplified];
    })
    .flat(),
);

let step = 0.9;
let dots = sampleLand(step);
if (dots.length > 25_000) {
  step = 1.1;
  dots = sampleLand(step);
}

await mkdir(geoDirectory, { recursive: true });
await writeFile(dotsPath, JSON.stringify(dots));
await writeFile(coastlinePath, JSON.stringify(coastlines));

const dotBytes = Buffer.byteLength(JSON.stringify(dots));
const coastlineBytes = Buffer.byteLength(JSON.stringify(coastlines));
console.log(`Generated ${dots.length} land dots at ${step}° sampling.`);
console.log(`land-dots.json: ${dotBytes} bytes`);
console.log(`coastline-50m.json: ${coastlineBytes} bytes (${coastlines.length} paths)`);
