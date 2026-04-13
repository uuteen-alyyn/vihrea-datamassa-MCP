import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

export function registerHaeKantaPrompt(server: McpServer): void {
  server.prompt(
    "hae_kanta",
    "Hae Vihreiden kanta annettuun aiheeseen",
    { aihe: z.string().describe("Aihe tai kysymys suomeksi") },
    ({ aihe }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `Hae Vihreiden kanta aiheeseen: "${aihe}"

Ohje:
1. Kutsu search_chunks hakutermillä joka kuvaa aihetta.
2. Jos tulos on tyhjä (0 chunkkia), muotoile hakutermi eri sanastolla ja kutsu uudelleen attempt-arvolla 2.
3. Jos toinenkin yritys tuottaa 0 tulosta, kokeile vielä kerran attempt-arvolla 3 eri lähestymisellä.
4. Muodosta vastaus löydetyistä chunkeista. Mainitse aina lähdeohjelma ja URL jokaisen väitteen yhteydessä.
5. Jos kaikki 3 yritystä palauttavat 0 tulosta, kerro suoraan ettei aiheesta löydy tietoa korpuksesta — älä keksi kantoja.`,
          },
        },
      ],
    })
  );
}
