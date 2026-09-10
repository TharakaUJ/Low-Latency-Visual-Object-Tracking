#include <stdio.h>
#include <stdint.h>

// ============================================================================
// Avalon-MM Slave Base Address Configuration
// Replace this with the actual physical base address assigned in Platform Designer (Qsys)
// ============================================================================
#define AVALON_SLAVE_BASE      0x00022000  // Example base address

// ============================================================================
// Register Offset Macros (Word Indices converted to Byte Addresses)
// ============================================================================
#define REG_BYTES              4           // 32-bit data width = 4 bytes per word

#define ADDR_BOUND_X          (AVALON_SLAVE_BASE + (0 * REG_BYTES)) // 0x00
#define ADDR_BOUND_Y          (AVALON_SLAVE_BASE + (1 * REG_BYTES)) // 0x04
#define ADDR_TMPL_BASE        (AVALON_SLAVE_BASE + (2 * REG_BYTES)) // 0x08

// Dynamic macro to fetch any template register by its specific array index (0 to 255)
#define ADDR_TMPL_REG(idx)    (ADDR_TMPL_BASE + ((idx) * REG_BYTES))

// Dynamic macro to fetch template register using 2D (row, col) coordinates (16x16 grid)
#define WIN_SIZE              16
#define ADDR_TMPL_XY(row, col) (ADDR_TMPL_BASE + ((((row) * WIN_SIZE) + (col)) * REG_BYTES))

// ============================================================================
// Hardware Abstraction Layer (HAL) Read Macro
// ============================================================================
// Uses volatile to prevent the compiler from caching memory reads
#define READ_REG(addr)        (*((volatile uint32_t *)(addr)))

// ============================================================================
// Test Main Application
// ============================================================================
int main(void) {
    // Standard printf handles multi-line transitions and string formatting reliably
    printf("Starting Avalon Slave Memory Read Test...\n\n");

    // 1. Read Boundary Registers
    uint32_t bound_x = READ_REG(ADDR_BOUND_X);
    uint32_t bound_y = READ_REG(ADDR_BOUND_Y);

    // Mask to 10 bits as defined in the Verilog code [9:0]
    bound_x &= 0x3FF;
    bound_y &= 0x3FF;

    printf("--- Boundary Registers ---\n");
    // Standard printf handles unsigned %u and padded 8-character hex %08X seamlessly
    printf("Boundary X: %u (Target Byte Addr: 0x%08X)\n", bound_x, (unsigned int)ADDR_BOUND_X);
    printf("Boundary Y: %u (Target Byte Addr: 0x%08X)\n\n", bound_y, (unsigned int)ADDR_BOUND_Y);

    // 2. Read Linear Template Array (First 5 elements as a sample)
    printf("--- Template Mirror Array (Linear Index Sample) ---\n");
    for (int i = 0; i < 5; i++) {
        uint32_t tmpl_val = READ_REG(ADDR_TMPL_REG(i)) & 0xFF; // Mask to 8 bits [7:0]
        // Standard printf correctly maps %d to loop counts and %02X to padded 8-bit hex
        printf("Template[%d]: 0x%02X (Target Byte Addr: 0x%08X)\n", i, (unsigned int)tmpl_val, (unsigned int)ADDR_TMPL_REG(i));
    }
    printf("\n");

    // 3. Read Template Array using 2D Grid Coordinates (Row 0, Col 0 to Col 3)
    printf("--- Template Mirror Array (2D Matrix Sample) ---\n");
    int target_row = 0;
    for (int target_col = 0; target_col < 4; target_col++) {
        uint32_t tmpl_val = READ_REG(ADDR_TMPL_XY(target_row, target_col)) & 0xFF;
        printf("Template[Row %d][Col %d]: 0x%02X (Target Byte Addr: 0x%08X)\n", 
               target_row, target_col, (unsigned int)tmpl_val, (unsigned int)ADDR_TMPL_XY(target_row, target_col));
    }

    return 0;
}
