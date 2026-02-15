# Shipping Cost Model: China to US/EU Kickstarter Backers

Estimated costs for shipping batches of 1-10 retro ICs from China to
Kickstarter backers. Assumes ~3,000 units total, split 50% US / 50% EU.

## Assumptions

| Parameter | Value |
|---|---|
| Total units | ~3,000 ICs |
| Split | 50% US (1,500), 50% EU (1,500) |
| IC weight | ~7 g each (DIP-48 package) |
| Packaging per IC | ~3 g (anti-static bag + foam) |
| Outer packaging | Padded mailer ~20 g, small box ~40 g |
| Declared value | ~$50-70 per IC (median from scraped data) |

## Strategy A: Direct ship from China (ePacket per order)

ePacket rate: 23 CNY + 85 CNY/kg (~$3.15 + $11.65/kg at 7.3 CNY/USD).

| ICs per order | Package weight | ePacket to US | China Post to EU | Est. orders (3,000 ICs) |
|---|---|---|---|---|
| 1 | ~50 g | $3.73 | $4.50 | 3,000 |
| 2 | ~60 g | $3.85 | $4.70 | 1,500 |
| 3 | ~70 g | $3.97 | $4.90 | 1,000 |
| 5 | ~95 g | $4.26 | $5.30 | 600 |
| 10 | ~140 g | $4.78 | $5.90 | 300 |

### Additional costs (direct ship)

- **US:** De minimis is gone -- every package needs a customs declaration.
  Semiconductors (HTS 8541/8542) are duty-free under the Information
  Technology Agreement, but customs processing adds friction and potential
  broker fees.
- **EU:** VAT ~20% collected via IOSS at checkout. From **July 2026** a
  flat **EUR 3 per parcel** customs levy applies to low-value imports.
- **Packaging materials:** ~$0.30-0.50 per order.

### Direct ship total estimate per order

| ICs | US (incl. customs) | EU (incl. VAT handling + EUR 3 levy) |
|---|---|---|
| 1 | ~$4.50 | ~$8.50 |
| 3 | ~$4.80 | ~$9.00 |
| 5 | ~$5.10 | ~$9.40 |
| 10 | ~$5.70 | ~$10.10 |

At 3,000 individual shipments this totals **$12,000-20,000** depending on
order sizes, and carries the risk of customs delays, lost packages, and
limited tracking on cheaper options.

## Strategy B: Bulk freight to regional warehouses + domestic last mile (Recommended)

At 3,000 units this is clearly the better approach.

### Step 1: Bulk freight from China

3,000 ICs = ~21 kg of ICs + packaging = one small carton (~25-30 kg, 0.05 CBM).

| Method | Cost | Transit |
|---|---|---|
| Air freight (DHL/FedEx) | ~$300-500 to US, ~$350-550 to EU | 3-5 days |
| Sea freight (LCL) | ~$150-250 per destination | 25-35 days |

Split shipment to both regions: **~$500-800 total**. That is ~$0.17-0.27
per IC.

- **US customs:** Semiconductors are duty-free (ITA). Customs broker for
  a commercial shipment: ~$150-250.
- **EU customs:** 0% duty (ITA) + import VAT ~20% on declared value
  (reclaimable if VAT-registered). Customs broker: ~EUR 150-250.

### Step 2: 3PL pick and pack

| Cost element | Per order |
|---|---|
| Pick and pack fee | $2.00-3.00 |
| Packaging materials | $0.30-0.50 |
| Per additional IC | $0.15-0.25 |

### Step 3: Domestic last mile

| ICs | Weight | US (USPS First Class) | EU (local post, avg) |
|---|---|---|---|
| 1 | ~30 g | $3.50 | EUR 3.00 |
| 2 | ~40 g | $3.50 | EUR 3.00 |
| 3 | ~50 g | $3.75 | EUR 3.20 |
| 5 | ~70 g | $4.00 | EUR 3.50 |
| 10 | ~110 g | $4.50 | EUR 4.00 |

### Strategy B total cost per order

| ICs per order | US total | EU total |
|---|---|---|
| 1 | **$6.00-7.00** | **EUR 6.50-7.50** |
| 2 | $6.15-7.15 | EUR 6.65-7.65 |
| 3 | $6.35-7.35 | EUR 6.85-7.85 |
| 5 | $6.75-7.75 | EUR 7.25-8.25 |
| 10 | $7.60-8.60 | EUR 8.10-9.10 |

Plus one-time fixed costs:

| Item | Cost |
|---|---|
| Bulk freight (2 destinations) | $500-800 |
| Customs brokerage (US + EU) | $300-500 |
| Warehouse / setup fees | $200-400 |
| **Fixed overhead total** | **$1,000-1,700** |

## Budget Summary

Using Strategy B (bulk freight + regional 3PL), assuming an average order
size of ~3 ICs and ~800 total orders:

| Line item | Cost |
|---|---|
| Fixed overhead | $1,300 |
| US orders (~400 x $7.00) | $2,800 |
| EU orders (~400 x EUR 7.50 ~ $8.10) | $3,240 |
| 15% contingency buffer | $1,100 |
| **Total shipping budget** | **~$8,450** |
| **Per IC shipped** | **~$2.80** |

## Suggested Kickstarter Pledge Shipping Add-ons

Includes margin over cost to cover fixed overhead and contingency.

| Tier | ICs | US | EU |
|---|---|---|---|
| Single IC | 1 | $8 | $10 |
| Small set | 3-5 | $10 | $12 |
| Full set | 8-10 | $12 | $14 |

## Key Risks

1. **US tariffs are volatile.** Semiconductors are currently exempt from
   reciprocal tariffs (HTS 8541/8542), but this could change. Add 10-15%
   buffer.
2. **EU EUR 3 levy** kicks in July 2026 for direct-to-consumer parcels.
   Using a regional warehouse with bulk import avoids this.
3. **VAT handling.** EU backers may expect VAT-inclusive pricing. Budget
   ~20% on declared value if not VAT-registered.
4. **Returns and replacements.** Budget 3-5% of units for re-shipping
   dead or wrong ICs.

## Sources

- [China Post ePacket Rates](https://www.chinapostaltracking.com/ems/epacket-rate/)
- [Kickstarter Shipping Costs Guide](https://www.crowdcrux.com/a-guide-to-kickstarter-shipping-costs/)
- [EU EUR 3 Customs Duty on Low-Value Parcels (July 2026)](https://www.consilium.europa.eu/en/press/press-releases/2025/12/12/customs-council-agrees-to-levy-customs-duty-on-small-parcels-as-of-1-july-2026/)
- [Semiconductor Tariff Guide](https://www.cofactr.com/articles/definitive-guide-to-semiconductor-tariffs)
- [US Tariff Tracker 2026](https://www.tradecomplianceresourcehub.com/2026/02/05/trump-2-0-tariff-tracker/)
- [EU De Minimis Exemption Ending](https://www.avalara.com/blog/en/europe/2025/11/eu-end-150-customs-duty-exemption-2026.html)
- [Kickstarter Fulfillment Guide](https://www.efulfillmentservice.com/2025/05/international-shipping-for-kickstarter-rewards-a-guide/)
