# Title: Wrong calculation at Sustainability Journal
## Repro Steps:

## Description:
Use **CRONUS USA, Inc.** company:

1. Install Sustainability demo data in Contoso Demo Tool.
2. Open **Sustainability Account Categories**.
3. Find **PURCHGOODS-GL** code.
4. in the **G/L Account** field enter **61300** account (or any other with the balance).
5. Close the page and open **Sustainability Journal** with **DEFAULT** batch.
6. The last line in this journal is with the **Account No. = 13151** and the **Installation Multiplier** for this line has value **1; Emission Factor CO2** for this line is **0.15**.
7. Add **Unit of Measure**.
8. Run the **Collect Amount from G/L Entries** action (from Line).
9. You will see **Net Change** used as a source for this calculation (for account I mentioned, it should be **-52,818.18**). Press OK.
10. After running the action, we will get the following results:
   a. Custom Amount = -52,818.18 (WRONG)
    b. Emission CO2 = -7,922.727 (WRONG)

EXPECTED RESULTS:
====================================
**Custom Amount** when use action **Collect Amount from G/L Entries** always must show positive value. So, if this is the case, Emissions will be calculated properly.
