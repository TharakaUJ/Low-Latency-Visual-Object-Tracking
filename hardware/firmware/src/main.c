#include <sys/alt_stdio.h> // Contains alt_printf
#include <stdint.h>
#include <io.h>            // Contains the official Intel/Altera cache-bypassing I/O macros

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
// IORD_32DIRECT uses specific assembly instructions to bypass the CPU data cache
#define READ_REG(addr)        IORD_32DIRECT(addr, 0)

// ============================================================================
// Test Main Application
// ============================================================================
int main(void) {
    // alt_printf handles basic multiline text
    alt_printf("Starting Avalon Slave Memory Read Test (Cache Bypassed)...\n\n");

    // 1. Read Boundary Registers
    uint32_t bound_x = READ_REG(ADDR_BOUND_X);
    uint32_t bound_y = READ_REG(ADDR_BOUND_Y);

    // Mask to 10 bits as defined in the Verilog code [9:0]
    bound_x &= 0x3FF;
    bound_y &= 0x3FF;

    alt_printf("--- Boundary Registers ---\n");
    // alt_printf restriction: %u and %08X are unsupported. Used %d and %x instead.
    alt_printf("Boundary X: %d (Target Byte Addr: 0x%x)\n", (int)bound_x, (unsigned int)ADDR_BOUND_X);
    alt_printf("Boundary Y: %d (Target Byte Addr: 0x%x)\n\n", (int)bound_y, (unsigned int)ADDR_BOUND_Y);

    // 2. Read Linear Template Array (First 5 elements as a sample)
    alt_printf("--- Template Mirror Array (Linear Index Sample) ---\n");
    for (int i = 0; i < 5; i++) {
        uint32_t tmpl_val = READ_REG(ADDR_TMPL_REG(i)) & 0xFF; // Mask to 8 bits [7:0]
        // alt_printf restriction: %02X is unsupported. Used %x instead.
        alt_printf("Template[%d]: 0x%x (Target Byte Addr: 0x%x)\n", i, (unsigned int)tmpl_val, (unsigned int)ADDR_TMPL_REG(i));
    }
    alt_printf("\n");

    // 3. Read Template Array using 2D Grid Coordinates (Row 0, Col 0 to Col 3)
    alt_printf("--- Template Mirror Array (2D Matrix Sample) ---\n");
    int target_row = 0;
    for (int target_col = 0; target_col < 4; target_col++) {
        uint32_t tmpl_val = READ_REG(ADDR_TMPL_XY(target_row, target_col)) & 0xFF;
        alt_printf("Template[Row %d][Col %d]: 0x%x (Target Byte Addr: 0x%x)\n", 
                   target_row, target_col, (unsigned int)tmpl_val, (unsigned int)ADDR_TMPL_XY(target_row, target_col));
    }


    while (1) {
        uint32_t bound_x = READ_REG(ADDR_BOUND_X) & 0x3FF;
        uint32_t bound_y = READ_REG(ADDR_BOUND_Y) & 0x3FF;

        alt_printf("Boundary X: %d (Target Byte Addr: 0x%x)\n", (int)bound_x, (unsigned int)ADDR_BOUND_X);
        alt_printf("Boundary Y: %d (Target Byte Addr: 0x%x)\n\n", (int)bound_y, (unsigned int)ADDR_BOUND_Y);

        usleep(1000000);
    }
    return 0;
}
